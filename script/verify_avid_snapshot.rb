#!/usr/bin/env ruby
# Verify the unmodified shared SDK source before building an application adapter.
require 'digest'
require 'json'
require 'pathname'
require 'find'
require 'set'

root = File.expand_path('..', __dir__)
vendor = File.join(root, 'vendor')
manifest_path = File.join(vendor, 'AVID_CORE_TRANSCRIPTION_SOURCE_MANIFEST.json')
expected_manifest = '7dcb2311c335a8b06fb91e160ee8441337a02ddb17b8b03fb14c1f3a0f110a27'
abort 'AVID Core source manifest integrity check failed' unless Digest::SHA256.file(manifest_path).hexdigest == expected_manifest
manifest = JSON.parse(File.binread(manifest_path))
expected_archive = '76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3'
abort 'Unexpected AVID Core source identity' unless manifest.fetch('source_bundle_sha256') == expected_archive
archive = File.join(vendor, 'AVID_CORE_TRANSCRIPTION_SOURCE.tar.gz')
abort 'AVID Core archive integrity check failed' unless Digest::SHA256.file(archive).hexdigest == expected_archive
source = File.join(vendor, 'avid-core-transcription')
abort 'Shared source root is missing or linked' unless File.directory?(source) && !File.symlink?(source)
manifest.fetch('files').each do |entry|
  relative = Pathname.new(entry.fetch('path'))
  abort "Unsafe source path: #{relative}" if relative.absolute? || relative.each_filename.include?('..')
  path = File.join(source, relative.to_s)
  abort "Missing or linked shared source: #{relative}" unless File.file?(path) && !File.symlink?(path)
  abort "Source escapes snapshot: #{relative}" unless File.realpath(path).start_with?(File.realpath(source) + '/')
  unless File.size(path) == entry.fetch('size_bytes') && Digest::SHA256.file(path).hexdigest == entry.fetch('sha256')
    abort "AVID Core shared source changed: #{relative}; obtain a newly reviewed snapshot instead of an application fork"
  end
end
# SwiftPM compiles newly added sources/resources too. A list of matching hashes
# alone cannot authenticate the source tree if additional files are ignored.
expected_files = manifest.fetch('files').map { |entry| entry.fetch('path') }.to_set
# These are generated output roots, not blanket filename/directory exemptions.
# A nested .build under Sources is deliberately not exempted.
generated_roots = [
  'apple/AVIDTranscription/.build',
  'apple/AVIDTranscription/.swiftpm',
  'apple/AVIDTranscriptionEngines/.build',
  'apple/AVIDTranscriptionEngines/.swiftpm',
  'script/__pycache__'
].to_set
Find.find(source) do |path|
  next if path == source
  relative = Pathname.new(path).relative_path_from(Pathname.new(source)).to_s
  abort "Linked shared source/output path: #{relative}" if File.symlink?(path)
  if generated_roots.include?(relative) && File.directory?(path)
    Find.prune
  end
  next if File.directory?(path)
  abort "Unexpected shared source file: #{relative}" unless expected_files.include?(relative)
  abort "Special shared source file: #{relative}" unless File.file?(path)
end
puts "AVID Core snapshot verified: #{manifest.fetch('files').length} files; #{expected_archive}"
