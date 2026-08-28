import Foundation
import AVFoundation
import MediaPlayer
import UIKit

/// Chapter playback. Each paragraph is its own MP3, so a chapter is an
/// AVQueuePlayer of paragraph items; the queue advances on its own, which is
/// what keeps playback alive with the screen off.
@Observable
@MainActor
final class Player {
    private(set) var isPlaying = false
    private(set) var positionMs: Int = 0
    private(set) var totalMs: Int = 0
    private(set) var currentTokenIndex: Int?
    private(set) var tokens: [Token] = []

    var rate: Float = 1.0 {
        didSet {
            // defaultRate is what AVQueuePlayer restores when it advances to
            // the next paragraph item; setting only `rate` let every paragraph
            // and chapter boundary snap playback back to 1.0×.
            queue?.defaultRate = rate
            queue?.rate = isPlaying ? rate : 0
            updateNowPlaying()
        }
    }

    private var queue: AVQueuePlayer?
    private var items: [AVPlayerItem] = []
    private var paragraphStarts: [Int] = []      // ms offset per paragraph
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?
    private var itemObservation: NSKeyValueObservation?
    private var rateObservation: NSKeyValueObservation?

    private var book: Book?
    private var chapter: Chapter?
    private var artwork: MPMediaItemArtwork?

    /// Called when a chapter finishes so the app can roll into the next one.
    var onChapterEnd: (() -> Void)?

    init() {
        configureSession()
        configureRemoteCommands()
    }

    deinit {
        // Observers are torn down in `stop()`, which every load path calls
        // before replacing the queue; nothing to release from a nonisolated
        // deinit.
    }

    // MARK: - Session

    private func configureSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            // .playback keeps audio alive when the screen locks and when the
            // silent switch is on — both required for an audiobook.
            try session.setCategory(.playback, mode: .spokenAudio, policy: .longFormAudio)
            try session.setActive(true)
        } catch {
            // Non-fatal: playback still works, just without the long-form policy.
        }
    }

    // MARK: - Loading

    func load(book: Book, chapter: Chapter, manifest: Manifest, library: Library,
              downloads: Downloads? = nil, startAtMs: Int = 0, autoplay: Bool = false) {
        stop()

        self.book = book
        self.chapter = chapter
        tokens = TokenBuilder.build(chapter: chapter, manifest: manifest)
        totalMs = manifest.totalMs
        paragraphStarts = manifest.paragraphs.map(\.startMs)

        items = manifest.paragraphs.map { para in
            // A downloaded copy wins, so an offline book never touches the network.
            let url = downloads?.localURL(slug: book.slug, relativePath: para.audio)
                ?? library.audioURL(slug: book.slug, relativePath: para.audio)
            let item = AVPlayerItem(url: url)
            // Speech held at 1.5×–2× stays intelligible with the time-domain
            // algorithm; the default smears consonants.
            item.audioTimePitchAlgorithm = .timeDomain
            return item
        }
        let q = AVQueuePlayer(items: items)
        q.actionAtItemEnd = .advance
        q.defaultRate = rate
        queue = q

        addObservers()
        loadArtwork(url: library.coverURL(slug: book.slug))
        seek(toMs: startAtMs)
        updateNowPlaying()

        if autoplay { play() }
    }

    func stop() {
        pause()
        if let timeObserver { queue?.removeTimeObserver(timeObserver) }
        timeObserver = nil
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = nil
        itemObservation?.invalidate()
        itemObservation = nil
        rateObservation?.invalidate()
        rateObservation = nil
        queue?.removeAllItems()
        queue = nil
        items = []
        tokens = []
        currentTokenIndex = nil
        positionMs = 0
        totalMs = 0
    }

    private func addObservers() {
        guard let queue else { return }
        // 20 Hz is enough to land on the right word without burning battery.
        let interval = CMTime(seconds: 0.05, preferredTimescale: 600)
        timeObserver = queue.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        // Belt and braces: AVQueuePlayer has historically reset `rate` on an
        // item transition even with defaultRate set. Re-pin it if it drifts
        // while we believe we are playing.
        itemObservation = queue.observe(\.currentItem, options: [.new]) { [weak self] player, _ in
            MainActor.assumeIsolated {
                guard let self, self.isPlaying else { return }
                player.defaultRate = self.rate
                if player.rate != 0, player.rate != self.rate { player.rate = self.rate }
            }
        }
        rateObservation = queue.observe(\.rate, options: [.new]) { [weak self] player, _ in
            MainActor.assumeIsolated {
                guard let self, self.isPlaying, player.rate != 0,
                      player.rate != self.rate else { return }
                player.rate = self.rate
            }
        }
        endObserver = NotificationCenter.default.addObserver(
            forName: AVPlayerItem.didPlayToEndTimeNotification,
            object: items.last, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.isPlaying = false
                self.updateNowPlaying()
                self.onChapterEnd?()
            }
        }
    }

    // MARK: - Transport

    func play() {
        guard let queue else { return }
        queue.defaultRate = rate
        queue.rate = rate
        isPlaying = true
        updateNowPlaying()
    }

    func pause() {
        queue?.pause()
        isPlaying = false
        updateNowPlaying()
    }

    func toggle() { isPlaying ? pause() : play() }

    func skip(seconds: Double) {
        seek(toMs: max(0, min(totalMs, positionMs + Int(seconds * 1000))))
    }

    /// Absolute seek inside the chapter, across paragraph boundaries.
    func seek(toMs ms: Int) {
        guard let queue, !items.isEmpty else { return }
        let clamped = max(0, min(ms, max(0, totalMs - 50)))
        let target = paragraphIndex(forMs: clamped)
        let within = Double(clamped - paragraphStarts[target]) / 1000.0

        let wasPlaying = isPlaying
        queue.pause()
        queue.removeAllItems()
        for item in items[target...] {
            item.seek(to: .zero, completionHandler: nil)
            if queue.canInsert(item, after: nil) { queue.insert(item, after: nil) }
        }
        queue.seek(to: CMTime(seconds: within, preferredTimescale: 600)) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if wasPlaying { self.play() }
                self.tick()
            }
        }
        positionMs = clamped
        updateTokenIndex()
    }

    func seek(toToken token: Token) { seek(toMs: token.startMs) }

    // MARK: - Ticking

    private func tick() {
        guard let queue, let item = queue.currentItem,
              let index = items.firstIndex(of: item) else { return }
        let within = Int(CMTimeGetSeconds(item.currentTime()) * 1000)
        guard within >= 0 else { return }
        positionMs = min(totalMs, paragraphStarts[index] + within)
        isPlaying = queue.timeControlStatus == .playing
        updateTokenIndex()
        updateNowPlayingPosition()
    }

    private func updateTokenIndex() {
        guard !tokens.isEmpty else { currentTokenIndex = nil; return }
        if let i = tokens.firstIndex(where: { positionMs < $0.endMs }) {
            currentTokenIndex = i
        } else {
            currentTokenIndex = tokens.count - 1
        }
    }

    private func paragraphIndex(forMs ms: Int) -> Int {
        var idx = 0
        for (i, start) in paragraphStarts.enumerated() where ms >= start { idx = i }
        return idx
    }

    // MARK: - Lock screen

    private func loadArtwork(url: URL) {
        Task { [weak self] in
            guard let (data, _) = try? await URLSession.shared.data(from: url),
                  let image = UIImage(data: data) else { return }
            // MediaPlayer invokes this handler off the main actor, so it must
            // be built outside actor isolation or Swift 6 traps at runtime.
            let art = Self.makeArtwork(image)
            await MainActor.run {
                self?.artwork = art
                self?.updateNowPlaying()
            }
        }
    }

    private nonisolated static func makeArtwork(_ image: UIImage) -> MPMediaItemArtwork {
        MPMediaItemArtwork(boundsSize: image.size) { _ in image }
    }

    private func updateNowPlaying() {
        guard let book, let chapter else {
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
            return
        }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: chapter.title,
            MPMediaItemPropertyArtist: book.author,
            MPMediaItemPropertyAlbumTitle: book.title,
            MPMediaItemPropertyPlaybackDuration: Double(totalMs) / 1000.0,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: Double(positionMs) / 1000.0,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? Double(rate) : 0.0,
            MPNowPlayingInfoPropertyIsLiveStream: false,
        ]
        if let artwork { info[MPMediaItemPropertyArtwork] = artwork }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func updateNowPlayingPosition() {
        guard var info = MPNowPlayingInfoCenter.default().nowPlayingInfo else { return }
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = Double(positionMs) / 1000.0
        info[MPNowPlayingInfoPropertyPlaybackRate] = isPlaying ? Double(rate) : 0.0
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func configureRemoteCommands() {
        let c = MPRemoteCommandCenter.shared()
        c.playCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.play() }
            return .success
        }
        c.pauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.pause() }
            return .success
        }
        c.togglePlayPauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.toggle() }
            return .success
        }
        c.skipForwardCommand.preferredIntervals = [15]
        c.skipForwardCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.skip(seconds: 15) }
            return .success
        }
        c.skipBackwardCommand.preferredIntervals = [15]
        c.skipBackwardCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.skip(seconds: -15) }
            return .success
        }
        c.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let e = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            Task { @MainActor in self?.seek(toMs: Int(e.positionTime * 1000)) }
            return .success
        }
    }
}
