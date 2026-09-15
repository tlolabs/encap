project('encap-linux', 'c', version: '2.0.1', default_options: ['c_std=c17', 'warning_level=3'])

gtk = dependency('gtk4', version: '>=4.10')
adwaita = dependency('libadwaita-1', version: '>=1.4')
json_glib = dependency('json-glib-1.0', version: '>=1.6')
gstreamer = dependency('gstreamer-1.0', version: '>=1.20')
pixbuf = dependency('gdk-pixbuf-2.0', version: '>=2.36')

executable(
  'encap',
  ['src/main.c', 'src/source_waveform.c', 'src/source_list.c', 'src/chapter_editor.c', 'src/chapter_names.c'],
  dependencies: [gtk, adwaita, json_glib, pixbuf, gstreamer],
  install: true,
)

install_data('com.tlolabs.encap.desktop', install_dir: get_option('datadir') / 'applications')
install_data('../../assets/icons/png/EnCap-256.png',
  rename: 'com.tlolabs.encap.png',
  install_dir: get_option('datadir') / 'icons/hicolor/256x256/apps')

chapter_names_test = executable('chapter-names-test',
  ['tests/chapter_names_test.c', 'src/chapter_names.c'],
  include_directories: include_directories('src'))
test('chapter timestamp parity', chapter_names_test,
  args: [meson.project_source_root() / '../../tests/fixtures/chapter-times.tsv'])

source_playback_test = executable('source-playback-test',
  ['tests/source_playback_test.c', 'src/source_waveform.c'],
  dependencies: [gtk, adwaita, json_glib, gstreamer])
test('source playback and media controls', source_playback_test,
  args: [meson.project_source_root() / '../../tests/fixtures/source-shuttle.tsv'], timeout: 60)
