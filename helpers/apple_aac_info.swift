import AudioToolbox
import Foundation

func fourCC(_ value: String) -> UInt32 {
    value.utf8.reduce(0) { ($0 << 8) | UInt32($1) }
}

var format = kAudioFormatMPEG4AAC
var propertySize: UInt32 = 0
let specifierSize = UInt32(MemoryLayout<UInt32>.size)
let infoStatus = AudioFormatGetPropertyInfo(
    kAudioFormatProperty_Encoders,
    specifierSize,
    &format,
    &propertySize
)

guard infoStatus == noErr else {
    print("Apple system-selected (component query failed)")
    exit(1)
}

let count = Int(propertySize) / MemoryLayout<AudioClassDescription>.size
guard count > 0 else {
    print("Unavailable")
    exit(0)
}

var encoders = Array(
    repeating: AudioClassDescription(mType: 0, mSubType: 0, mManufacturer: 0),
    count: count
)
let propertyStatus = AudioFormatGetProperty(
    kAudioFormatProperty_Encoders,
    specifierSize,
    &format,
    &propertySize,
    &encoders
)

guard propertyStatus == noErr else {
    print("Apple system-selected (component query failed)")
    exit(1)
}

let manufacturers = Set(encoders.map(\.mManufacturer))
let hasHardware = manufacturers.contains(fourCC("aphw"))
let hasSoftware = manufacturers.contains(fourCC("appl"))

if hasHardware && hasSoftware {
    print("Apple hardware and software available; system-selected")
} else if hasHardware {
    print("Apple hardware available; system-selected")
} else if hasSoftware {
    print("Apple software")
} else {
    print("Apple system-selected")
}
