// swift-tools-version: 6.2
import PackageDescription
let package = Package(
    name: "ComboCU",
    platforms: [.macOS(.v14)],
    products: [.library(name: "ComboCU", type: .dynamic, targets: ["ComboCUBridge"])],
    targets: [
        .target(name: "OpenComputerUseKit", exclude: ["Resources"]),
        .target(name: "ComboCUBridge", dependencies: ["OpenComputerUseKit"]),
    ]
)
