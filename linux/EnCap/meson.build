project('encap-linux', 'c', version: '0.2.1', default_options: ['c_std=c17', 'warning_level=3'])

gtk = dependency('gtk4', version: '>=4.10')
adwaita = dependency('libadwaita-1', version: '>=1.4')
json_glib = dependency('json-glib-1.0', version: '>=1.6')

executable(
  'encap',
  'src/main.c',
  dependencies: [gtk, adwaita, json_glib],
  install: true,
)

install_data('com.tlolabs.encap.desktop', install_dir: get_option('datadir') / 'applications')
install_data('../../assets/icons/png/EnCap-256.png',
  rename: 'com.tlolabs.encap.png',
  install_dir: get_option('datadir') / 'icons/hicolor/256x256/apps')
