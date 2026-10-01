using EnCap;
using System.Runtime.InteropServices;
using System.Text.Json;
namespace EnCap.Tests;

internal static class EngineIntegration
{
    public static async Task RunAsync(string executable, string playbackLibrary, string artwork)
    {
        var root = Path.Combine(Path.GetTempPath(), "encap-avalonia-integration-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var audio = Path.Combine(root, "recordings");
            Directory.CreateDirectory(audio);
            var wav = Path.Combine(audio, "10012026120000_音声.wav");
            using (var writer = new BinaryWriter(File.Create(wav)))
            {
                int bytes = 48000 * 2 * 2 * 3;
                writer.Write("RIFF"u8);
                writer.Write(36 + bytes);
                writer.Write("WAVEfmt "u8);
                writer.Write(16);
                writer.Write((short)1);
                writer.Write((short)2);
                writer.Write(48000);
                writer.Write(192000);
                writer.Write((short)4);
                writer.Write((short)16);
                writer.Write("data"u8);
                writer.Write(bytes);
                writer.Write(new byte[bytes]);
            }
            var engine = new EngineClient(executable, Path.Combine(root, "recovery.json"));
            var document = await engine.InspectAsync(audio);
            Require(document.AudioSources.Count == 1 && document.Chapters.Count == 1, "real engine import");
            Require((await engine.WaveformAsync(wav, CancellationToken.None)).Length > 0, "real waveform");
            document.Metadata.EpisodeTitle = "Shared UI integration";
            document.Metadata.ArtworkPath = artwork;
            document.TranscriptSegments = [new() { Text = "Preserved correction", Speaker = "Narrator", EndTimeSeconds = 2 }];
            var saved = await engine.SaveAsync(document, Path.Combine(root, "test.encap"));
            var reopened = await engine.OpenAsync(saved);
            Require(reopened.Metadata.EpisodeTitle == document.Metadata.EpisodeTitle && reopened.TranscriptSegments[0].Text == "Preserved correction", "real save/reopen");
            await engine.SaveRecoveryAsync(document);
            Require((await engine.LoadRecoveryAsync())?.Metadata.EpisodeTitle == document.Metadata.EpisodeTitle, "isolated recovery round-trip");
            await engine.ClearRecoveryAsync();
            Require(await engine.LoadRecoveryAsync() is null, "clear recovery");
            foreach (var kind in new[] { "txt", "srt" })
            {
                var path = await engine.ExportTranscriptAsync(document, Path.Combine(root, "transcript." + kind), kind);
                Require(File.ReadAllText(path).Contains("Preserved correction"), "real " + kind + " export");
            }
            var mp3 = await engine.ExportAsync(document, Path.Combine(root, "audio.mp3"));
            Require(new FileInfo(mp3).Length > 0, "real MP3 export");
            document.ExportSettings.OutputFormat = "aac";
            document.ExportSettings.Encoder = "ffmpeg";
            var aac = await engine.ExportAsync(document, Path.Combine(root, "audio.m4a"));
            Require(new FileInfo(aac).Length > 0, "real AAC export");
            var v = document.Video.ExportSettings;
            v.Width = 320;
            v.Height = 240;
            v.Fps = 10;
            v.Encoding = "software";
            v.SelectionInitialized = true;
            v.SelectedChapterIds = document.Chapters.Select(c => c.Id).ToList();
            var mp4 = await engine.ExportVideoAsync(document, Path.Combine(root, "video.mp4"));
            Require(new FileInfo(mp4).Length > 0, "real MP4 export");
            NativeLibrary.SetDllImportResolver(typeof(NativePlayback).Assembly, (name, _, _) => name == "encap-playback" ? NativeLibrary.Load(playbackLibrary) : IntPtr.Zero);
            using (var player = new NativePlayback())
            {
                await player.OpenAsync(wav);
                player.Seek(1);
                player.Play(2);
                await Task.Delay(160);
                Require(player.Position > 1.15, "native forward rate");
                player.Pause();
                var paused = player.Position;
                await Task.Delay(80);
                Require(Math.Abs(player.Position - paused) < 0.001, "native pause");
                player.Seek(2);
                player.Play(-2);
                await Task.Delay(160);
                Require(player.Position < 1.85, "native reverse rate");
                player.Pause();
                player.Play(.5);
                await Task.Delay(160);
                Require(player.IsPlaying && player.Rate == .5, "native half speed");
            }
            Require(File.Exists(wav), "original recording retained");
        }
        finally { Directory.Delete(root, true); }
    }
    private static void Require(bool value, string label)
    {
        if (!value)
            throw new Exception(label);
        Console.WriteLine("PASS " + label);
    }
}
