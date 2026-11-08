#!/usr/bin/env ruby
# Verify the unmodified shared SDK source before building an application adapter.
require 'digest'
require 'json'
require 'pathname'

root = File.expand_path('..', __dir__)
vendor = File.join(root, 'vendor')
manifest_path = File.join(vendor, 'AVID_CORE_TRANSCRIPTION_SOURCE_MANIFEST.json')
expected_manifest = 'a254e146d03c6690db7fde724a2d09e89d479a1ead22e7bd2ee983f920dd97c3'
abort 'AVID Core source manifest integrity check failed' unless Digest::SHA256.file(manifest_path).hexdigest == expected_manifest
manifest = JSON.parse(File.binread(manifest_path))
expected_archive = 'a302200860bde5c47cd4aeabacefedefa30e6112248302925164589ce9f45937'
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
