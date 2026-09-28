// OCR page images with macOS Vision (accurate, en-US, language correction).
// Usage: ocr_vision <image>...   -> prints one JSON object per image on stdout:
//   {"image": path, "lines": [{"text", "confidence", "x", "y", "w", "h"}]}
// Coordinates are Vision's: normalized, origin bottom-left. Compiled on demand by build_book.py.
import AppKit
import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    autoreleasepool {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["en-US"]
        request.usesLanguageCorrection = true
        do {
            try VNImageRequestHandler(url: URL(fileURLWithPath: path)).perform([request])
        } catch {
            FileHandle.standardError.write("OCR error \(path): \(error)\n".data(using: .utf8)!)
            exit(1)
        }
        let lines: [[String: Any]] = (request.results ?? []).compactMap { r in
            guard let c = r.topCandidates(1).first else { return nil }
            let b = r.boundingBox
            return ["text": c.string, "confidence": c.confidence, "x": b.minX, "y": b.minY, "w": b.width, "h": b.height]
        }
        let obj: [String: Any] = ["image": path, "lines": lines]
        let data = try! JSONSerialization.data(withJSONObject: obj)
        print(String(data: data, encoding: .utf8)!)
    }
}
