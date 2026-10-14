// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "tab-switcher",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.8.1"),
    ],
    targets: [
        .target(name: "EventTapLifecycle"),
        .target(name: "CompanionPolicy"),
        .testTarget(name: "CompanionPolicyTests", dependencies: ["CompanionPolicy"]),
        .testTarget(name: "EventTapLifecycleTests", dependencies: ["EventTapLifecycle"]),
        .executableTarget(
            name: "tab-switcher",
            dependencies: [
                "EventTapLifecycle",
                "CompanionPolicy",
                .product(name: "Sparkle", package: "Sparkle"),
            ],
            path: "Sources/tab-switcher",
            swiftSettings: [
                .enableUpcomingFeature("ExistentialAny")
            ]
        )
    ]
)
