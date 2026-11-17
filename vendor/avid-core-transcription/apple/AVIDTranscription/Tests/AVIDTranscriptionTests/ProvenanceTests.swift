import Foundation
import XCTest
@testable import AVIDTranscription

final class ProvenanceTests: XCTestCase {
    private func sharedFixture() throws -> Data {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        return try Data(contentsOf: root.appendingPathComponent("tests/fixtures/transcript-provenance-v1.json"))
    }

    func testRustSwiftSharedIdentityRoundTripAndLegacyUnknownPins() throws {
        let data = try sharedFixture()
        let transcript = try JSONDecoder().decode(Transcript.self, from: data)
        try transcript.validate()
        let original = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let encoded = try JSONEncoder().encode(transcript)
        let roundtrip = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertEqual(original["provenance"] as? NSDictionary, roundtrip["provenance"] as? NSDictionary)
        XCTAssertEqual(original["alignmentProvenance"] as? NSDictionary, roundtrip["alignmentProvenance"] as? NSDictionary)
        XCTAssertEqual(transcript.provenance.modelIdentity?.artifacts.count, 2)
        XCTAssertNotNil(transcript.provenance.runtimeBuildSHA256)

        let legacy = Data(#"{"engineID":"legacy","modelID":"selected-model"}"#.utf8)
        let unknown = try JSONDecoder().decode(TranscriptProvenance.self, from: legacy)
        XCTAssertNil(unknown.modelIdentity)
        XCTAssertNil(unknown.runtimeRevisions)
        XCTAssertNil(unknown.runtimeBuildSHA256)
        XCTAssertEqual(unknown, TranscriptProvenance(engineID: "legacy", modelID: "selected-model"))
    }

    func testPinsPersistThroughOffsetsCorrectionsAndCaptionMapping() throws {
        let transcript = try JSONDecoder().decode(Transcript.self, from: sharedFixture())
        let shifted = try transcript.offsettingTimes(by: 10)
        XCTAssertEqual(shifted.provenance, transcript.provenance)
        XCTAssertEqual(shifted.alignmentProvenance, transcript.alignmentProvenance)
        let corrected = try shifted.correctingSegment(at: 0, text: "Edited text.")
        XCTAssertEqual(corrected.provenance, transcript.provenance)
        XCTAssertNil(corrected.alignmentProvenance)
        XCTAssertTrue(corrected.segments[0].words.isEmpty)
        _ = try CaptionBuilder.cues(from: transcript, window: CaptionWindow(timelineStartSeconds: 20))
        XCTAssertEqual(try JSONDecoder().decode(Transcript.self, from: JSONEncoder().encode(transcript)), transcript)
    }

    func testMalformedImmutableAndRuntimeIdentitiesAreRejected() throws {
        let valid = try XCTUnwrap(JSONSerialization.jsonObject(with: sharedFixture()) as? [String: Any])
        for mutate in [
            { (identity: inout [String: Any]) in identity["manifestSHA256"] = "" },
            { (identity: inout [String: Any]) in identity["revision"] = "not-a-revision" },
            { (identity: inout [String: Any]) in identity["installationID"] = "mismatched" },
            { (identity: inout [String: Any]) in identity["schemaVersion"] = 999 },
            { (identity: inout [String: Any]) in
                var artifacts = identity["artifacts"] as! [[String: Any]]
                artifacts[0]["path"] = "../escape"; identity["artifacts"] = artifacts
            },
            { (identity: inout [String: Any]) in
                var artifacts = identity["artifacts"] as! [[String: Any]]
                artifacts[1]["path"] = artifacts[0]["path"]; identity["artifacts"] = artifacts
            },
            { (identity: inout [String: Any]) in
                var artifacts = identity["artifacts"] as! [[String: Any]]
                artifacts[0]["path"] = "weights"; artifacts[1]["path"] = "weights/config"; identity["artifacts"] = artifacts
            },
        ] {
            var value = valid
            var provenance = value["provenance"] as! [String: Any]
            var identity = provenance["modelIdentity"] as! [String: Any]
            mutate(&identity); provenance["modelIdentity"] = identity; value["provenance"] = provenance
            XCTAssertThrowsError(try JSONDecoder().decode(Transcript.self, from: JSONSerialization.data(withJSONObject: value)))
        }
        for fields: [String: Any] in [
            ["runtimeRevisions": [String: String]()],
            ["runtimeRevisions": ["sdk": "bad"]],
            ["runtimeBuildSHA256": ""],
            ["engineID": "   "],
            ["modelID": "bad\0identity"],
        ] {
            var value = valid; var provenance = value["provenance"] as! [String: Any]
            fields.forEach { provenance[$0.key] = $0.value }; value["provenance"] = provenance
            XCTAssertThrowsError(try JSONDecoder().decode(Transcript.self, from: JSONSerialization.data(withJSONObject: value)))
        }
    }

    func testVerifiedDescriptorIdentityIncludesAuxiliaryTokenizerPinsWithoutChangingCacheIDs() throws {
        let descriptor = try ModelCatalog.bundled().model(id: "whisper-large-v3")
        let identity = try descriptor.provenanceIdentity()
        XCTAssertEqual(identity.installationID, descriptor.installationID)
        XCTAssertEqual(identity.installationID, descriptor.revision + "-" + String(identity.manifestSHA256.prefix(16)))
        XCTAssertEqual(identity.artifacts.count, descriptor.artifacts.count)
        XCTAssertTrue(identity.artifacts.contains { $0.repository != descriptor.repository })
        let installed = InstalledModel(descriptor: descriptor, directory: URL(fileURLWithPath: "/fixture/verified-model"))
        let request = try RecognitionRequest(audioURL: URL(fileURLWithPath: "/fixture/audio.wav"), installedModel: installed)
        try request.validate()
        XCTAssertEqual(request.modelIdentity, identity)
        XCTAssertEqual(request.modelID, descriptor.id)
    }

    func testOperationsRejectMalformedPinsFromDirectLegacyStyleConstruction() throws {
        let fixture = try JSONDecoder().decode(Transcript.self, from: sharedFixture())
        let malformed = try Transcript(segments: fixture.segments, provenance:
            TranscriptProvenance(engineID: "fixture", modelID: "fixture", runtimeRevisions: ["sdk": "main"]))
        XCTAssertThrowsError(try malformed.offsettingTimes(by: 0))
        XCTAssertThrowsError(try malformed.correctingSegment(at: 0, text: "edit"))
        XCTAssertThrowsError(try CaptionBuilder.cues(from: malformed))
    }
}
