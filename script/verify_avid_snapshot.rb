#!/usr/bin/env ruby
# Verify the unmodified shared SDK source before building an application adapter.
require 'digest'
require 'json'
require 'pathname'

root = File.expand_path('..', __dir__)
vendor = File.join(root, 'vendor')
manifest_path = File.join(vendor, 'AVID_CORE_TRANSCRIPTION_SOURCE_MANIFEST.json')
expected_manifest = 'f0232869d2068eb9c24b273238c3d9d510eaf6a7870561fc39052b4226b88397'
abort 'AVID Core source manifest integrity check failed' unless Digest::SHA256.file(manifest_path).hexdigest == expected_manifest
manifest = JSON.parse(File.binread(manifest_path))
expected_archive = 'f4555615571d54b96d714be26caf0484f6049835065d7215820c3244bf761c5a'
abort 'Unexpected AVID Core source identity' unless manifest.fetch('source_bundle_sha256') == expected_archive
archive = File.join(vendor, 'AVID_CORE_TRANSCRIPTION_SOURCE.tar.gz')
abort 'AVID Core archive integrity check failed' unless Digest::SHA256.file(archive).hexdigest == expected_archive
source = File.join(vendor, 'avid-core-transcription')
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
puts "AVID Core snapshot verified: #{manifest.fetch('files').length} files; #{expected_archive}"
