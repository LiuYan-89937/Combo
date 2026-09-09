import AppKit
import Foundation

private enum ApplicationIconRenderer {
    private static let iconPixelSize = 64

    static func dataURL(for application: NSRunningApplication) -> String? {
        guard let source = application.icon else {
            return nil
        }

        var proposedRect = NSRect(
            origin: .zero,
            size: NSSize(width: iconPixelSize, height: iconPixelSize)
        )
        guard
            let sourceImage = source.cgImage(
                forProposedRect: &proposedRect,
                context: nil,
                hints: nil
            ),
            let context = CGContext(
                data: nil,
                width: iconPixelSize,
                height: iconPixelSize,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            )
        else {
            return nil
        }

        context.interpolationQuality = .high
        context.draw(
            sourceImage,
            in: CGRect(x: 0, y: 0, width: iconPixelSize, height: iconPixelSize)
        )
        guard
            let renderedImage = context.makeImage(),
            let pngData = NSBitmapImageRep(cgImage: renderedImage)
                .representation(using: .png, properties: [:])
        else {
            return nil
        }

        return "data:image/png;base64,\(pngData.base64EncodedString())"
    }
}

extension ToolResultApplication {
    init(snapshot: AppSnapshot) {
        let app = snapshot.app
        self.init(
            applicationIdentifier: app.bundleIdentifier ?? app.name,
            displayName: app.name,
            iconDataURL: ApplicationIconRenderer.dataURL(for: app.runningApplication),
            processID: Int(app.pid),
            windowID: snapshot.targetWindowID.map { Int($0) },
            windowTitle: snapshot.windowTitle ?? ""
        )
    }
}
