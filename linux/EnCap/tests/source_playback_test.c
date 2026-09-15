/* Include the native controller to exercise its real GStreamer seek path and MPRIS schema. */
#include "../src/source_list.c"
#include <stdio.h>

static void shuttle_cases(const gchar *path) {
  FILE *file = fopen(path, "r"); g_assert_nonnull(file);
  char line[160]; int count = 0;
  while (fgets(line, sizeof line, file)) {
    if (line[0] == '#') continue;
    double current, expected; int direction, slow;
    g_assert_cmpint(sscanf(line, "%lf %d %d %lf", &current, &direction, &slow, &expected), ==, 4);
    g_assert_cmpfloat(encap_shuttle_rate(current, direction, slow), ==, expected); count++;
  }
  fclose(file); g_assert_cmpint(count, >, 0);
}

static void playback_seek(void) {
  gchar *path = NULL; gint fd = g_file_open_tmp("encap-playback-XXXXXX.wav", &path, NULL);
  g_assert_cmpint(fd, >=, 0); close(fd);
  GError *error = NULL;
  GstElement *writer = gst_parse_launch("audiotestsrc wave=silence num-buffers=200 ! audio/x-raw,rate=48000,channels=1 ! wavenc ! filesink name=output", &error);
  g_assert_no_error(error); g_assert_nonnull(writer);
  GstElement *output = gst_bin_get_by_name(GST_BIN(writer), "output");
  g_object_set(output, "location", path, NULL); gst_object_unref(output);
  gst_element_set_state(writer, GST_STATE_PLAYING);
  GstBus *bus = gst_element_get_bus(writer);
  GstMessage *message = gst_bus_timed_pop_filtered(bus, 5 * GST_SECOND, GST_MESSAGE_EOS | GST_MESSAGE_ERROR);
  g_assert_nonnull(message); g_assert_cmpint(GST_MESSAGE_TYPE(message), ==, GST_MESSAGE_EOS);
  gst_message_unref(message); gst_object_unref(bus);
  gst_element_set_state(writer, GST_STATE_NULL); gst_object_unref(writer);

  SourceList state = {0};
  state.player = gst_element_factory_make("playbin", NULL); g_assert_nonnull(state.player);
  GstElement *sink = gst_element_factory_make("fakesink", NULL); g_assert_nonnull(sink);
  g_object_set(sink, "sync", TRUE, NULL);
  gchar *uri = g_filename_to_uri(path, NULL, NULL);
  g_object_set(state.player, "uri", uri, "audio-sink", sink, NULL); g_free(uri);
  gst_element_set_state(state.player, GST_STATE_PAUSED);
  g_assert_cmpint(gst_element_get_state(state.player, NULL, NULL, 5 * GST_SECOND), ==, GST_STATE_CHANGE_SUCCESS);
  state.ready = TRUE;
  const double rates[] = {1, 2, 4, 0.5, -1, -2, -0.5};
  for (guint i = 0; i < G_N_ELEMENTS(rates); i++) {
    gboolean accepted = seek_playback(&state, 2 * GST_SECOND, rates[i]);
    g_print("Rate %.1f: %s\n", rates[i], accepted ? "accepted" : "unsupported");
    // Some distribution WAV demuxers reject reverse rates. The controller must
    // propagate that refusal instead of claiming reverse playback succeeded.
    if (rates[i] > 0) g_assert_true(accepted);
    if (!accepted) continue;
    g_assert_cmpint(gst_element_get_state(state.player, NULL, NULL, 5 * GST_SECOND), !=, GST_STATE_CHANGE_FAILURE);
  }
  gst_element_set_state(state.player, GST_STATE_NULL); gst_object_unref(state.player);
  unlink(path); g_free(path);
}

static void media_schema(void) {
  GError *error = NULL;
  GDBusNodeInfo *info = g_dbus_node_info_new_for_xml(media_xml, &error);
  g_assert_no_error(error); g_assert_nonnull(info);
  GDBusInterfaceInfo *player = g_dbus_node_info_lookup_interface(info, media_player_interface);
  g_assert_nonnull(player);
  const gchar *methods[] = {"Play", "Pause", "PlayPause", "Stop", "Next", "Previous", "Seek", "SetPosition"};
  for (guint i = 0; i < G_N_ELEMENTS(methods); i++) g_assert_nonnull(g_dbus_interface_info_lookup_method(player, methods[i]));
  SourceList state = {0};
  GVariant *status = g_variant_ref_sink(media_property(NULL, NULL, NULL, NULL, "PlaybackStatus", NULL, &state));
  g_assert_cmpstr(g_variant_get_string(status, NULL), ==, "Stopped"); g_variant_unref(status);
  GVariant *metadata = g_variant_ref_sink(media_property(NULL, NULL, NULL, NULL, "Metadata", NULL, &state));
  g_assert_true(g_variant_is_of_type(metadata, G_VARIANT_TYPE("a{sv}"))); g_variant_unref(metadata);
  g_dbus_node_info_unref(info);
}

int main(int argc, char **argv) {
  g_assert_cmpint(argc, ==, 2);
  gst_init(&argc, &argv);
  shuttle_cases(argv[1]); playback_seek(); media_schema();
  g_print("Passed shared shuttle cases, real WAV rate/decoder capability checks, and MPRIS schema checks.\n");
  return 0;
}
