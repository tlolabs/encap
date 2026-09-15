#include "source_list.h"
#include "source_waveform.h"
#include <string.h>
#include <gst/gst.h>
#include <unistd.h>
#include "source_shuttle.h"

typedef struct {
  EnCapWaveforms *waveforms;
  GtkWidget *root;
  GtkWidget *list;
  GstElement *player;
  guint bus_watch;
  gboolean ready, playing, ended, slow, failed;
  guint held_keys;
  double rate;
  guint media_owner, media_registration[2];
  GDBusConnection *media_bus;
  GDBusNodeInfo *media_info;
  GtkWidget *active_button;
  gchar *active_path;
  EnCapAddSources add;
  EnCapRemoveSources remove;
  gpointer user_data;
} SourceList;

static void media_update(SourceList *state);
static void media_start(SourceList *state);
static void media_free(SourceList *state);

static void update_button(GtkWidget *button, gboolean playing) {
  if (!button) return;
  gtk_button_set_icon_name(GTK_BUTTON(button), playing ? "media-playback-pause-symbolic" : "media-playback-start-symbolic");
  const gchar *name = g_object_get_data(G_OBJECT(button), "source-name");
  gchar *label = g_strdup_printf("%s %s", playing ? "Pause" : "Play", name ? name : "recording");
  gtk_widget_set_tooltip_text(button, label);
  gtk_accessible_update_property(GTK_ACCESSIBLE(button), GTK_ACCESSIBLE_PROPERTY_LABEL, label, -1);
  g_free(label);
}

static gint64 playback_position(SourceList *state) {
  gint64 position = 0;
  if (state->player) gst_element_query_position(state->player, GST_FORMAT_TIME, &position);
  return MAX(0, position);
}

static void stop_playback(SourceList *state) {
  if (state->bus_watch) { g_source_remove(state->bus_watch); state->bus_watch = 0; }
  if (state->player) { gst_element_set_state(state->player, GST_STATE_NULL); gst_clear_object(&state->player); }
  state->playing = state->ready = state->ended = state->slow = state->failed = FALSE;
  state->rate = 1;
  update_button(state->active_button, FALSE);
  if (state->active_button) g_object_remove_weak_pointer(G_OBJECT(state->active_button), (gpointer *)&state->active_button);
  state->active_button = NULL;
  g_clear_pointer(&state->active_path, g_free);
  media_update(state);
}

void encap_source_list_stop(GtkWidget *widget) {
  if (widget) stop_playback(g_object_get_data(G_OBJECT(widget), "source-state"));
}

static void free_source_list(gpointer data) {
  SourceList *state = data;
  stop_playback(state);
  media_free(state);
  encap_waveforms_free(state->waveforms);
  g_free(state);
}

static void pause_playback(SourceList *state) {
  state->playing = FALSE;
  if (state->player) gst_element_set_state(state->player, GST_STATE_PAUSED);
  update_button(state->active_button, FALSE);
  media_update(state);
}

static void playback_error(SourceList *state, const gchar *message) {
  state->failed = TRUE;
  pause_playback(state);
  gtk_widget_set_tooltip_text(state->list, message);
  if (state->active_button) {
    gtk_widget_set_tooltip_text(state->active_button, message);
    gtk_accessible_update_property(GTK_ACCESSIBLE(state->active_button), GTK_ACCESSIBLE_PROPERTY_LABEL, message, -1);
  }
}

static gboolean seek_playback(SourceList *state, gint64 position, double rate) {
  if (!state->player || !state->ready) return FALSE;
  return gst_element_seek(state->player, rate, GST_FORMAT_TIME, GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_ACCURATE,
    GST_SEEK_TYPE_SET, rate > 0 ? position : 0,
    rate > 0 ? GST_SEEK_TYPE_NONE : GST_SEEK_TYPE_SET, rate > 0 ? -1 : position);
}

static void apply_rate(SourceList *state) {
  if (!state->ready || !state->playing) return;
  gint64 position = (state->ended && state->rate > 0) ? 0 : playback_position(state);
  state->ended = FALSE;
  if (!seek_playback(state, position, state->rate)) {
    gchar *message = g_strdup_printf("This recording’s Linux decoder does not support %.1f× playback.", state->rate);
    playback_error(state, message); g_free(message); return;
  }
  gst_element_set_state(state->player, GST_STATE_PLAYING);
  update_button(state->active_button, TRUE);
  gchar *hint = g_strdup_printf("Playing at %.1f×. Space: play/pause; J/K/L: reverse/pause/forward; hold K for half speed.", state->rate);
  gtk_widget_set_tooltip_text(state->list, hint); g_free(hint);
  media_update(state);
}

static gboolean playback_message(GstBus *bus, GstMessage *message, gpointer data) {
  (void)bus;
  SourceList *state = data;
  switch (GST_MESSAGE_TYPE(message)) {
    case GST_MESSAGE_ASYNC_DONE:
      if (!state->ready) { state->ready = TRUE; apply_rate(state); }
      break;
    case GST_MESSAGE_EOS:
      pause_playback(state); state->ended = TRUE; break;
    case GST_MESSAGE_ERROR: {
      GError *error = NULL; gst_message_parse_error(message, &error, NULL);
      playback_error(state, error ? error->message : "Audio preview unavailable.");
      g_clear_error(&error); break;
    }
    default: break;
  }
  return G_SOURCE_CONTINUE;
}

static void play_button(SourceList *state, GtkWidget *button, double rate) {
  if (!button) return;
  const gchar *path = g_object_get_data(G_OBJECT(button), "source-path");
  if (g_strcmp0(path, state->active_path) != 0 || !state->player || state->failed) {
    stop_playback(state);
    state->active_path = g_strdup(path);
    state->active_button = button;
    g_object_add_weak_pointer(G_OBJECT(button), (gpointer *)&state->active_button);
    if (!gst_init_check(NULL, NULL, NULL) || !(state->player = gst_element_factory_make("playbin", NULL))) {
      playback_error(state, "Install the GStreamer playback and WAV/AIFF decoder plugins to preview audio."); return;
    }
    gchar *uri = g_filename_to_uri(path, NULL, NULL);
    g_object_set(state->player, "uri", uri, NULL); g_free(uri);
    GstBus *bus = gst_element_get_bus(state->player);
    state->bus_watch = gst_bus_add_watch(bus, playback_message, state); gst_object_unref(bus);
    state->rate = rate; state->playing = TRUE;
    media_start(state);
    GstStateChangeReturn result = gst_element_set_state(state->player, GST_STATE_PAUSED);
    if (result == GST_STATE_CHANGE_FAILURE) playback_error(state, "Could not open this recording for playback.");
    else if (result == GST_STATE_CHANGE_SUCCESS) { state->ready = TRUE; apply_rate(state); }
  } else {
    state->rate = rate; state->playing = TRUE; apply_rate(state);
  }
  update_button(state->active_button, state->playing);
  media_update(state);
}

static void playback_clicked(GtkButton *button, gpointer user_data) {
  SourceList *state = user_data;
  if (state->active_button == GTK_WIDGET(button) && state->playing) pause_playback(state);
  else play_button(state, GTK_WIDGET(button), 1);
}

static GtkWidget *selected_button(SourceList *state) {
  GList *rows = gtk_list_box_get_selected_rows(GTK_LIST_BOX(state->list));
  GtkWidget *button = rows ? g_object_get_data(G_OBJECT(rows->data), "playback-button") : NULL;
  g_list_free(rows); return button;
}

static void row_activated(GtkListBox *list, GtkListBoxRow *row, gpointer data) {
  (void)list;
  play_button(data, g_object_get_data(G_OBJECT(row), "playback-button"), 1);
}

static GPtrArray *selected_paths(SourceList *state) {
  GPtrArray *paths = g_ptr_array_new_with_free_func(g_free);
  GList *rows = gtk_list_box_get_selected_rows(GTK_LIST_BOX(state->list));
  for (GList *item = rows; item; item = item->next) {
    const gchar *path = g_object_get_data(G_OBJECT(item->data), "source-path");
    if (path) g_ptr_array_add(paths, g_strdup(path));
  }
  g_list_free(rows);
  return paths;
}

static void deletion_response(AdwMessageDialog *dialog, gchar *response, gpointer user_data) {
  SourceList *state = user_data;
  if (g_str_equal(response, "delete")) {
    GPtrArray *paths = g_object_get_data(G_OBJECT(dialog), "source-paths");
    stop_playback(state);
    state->remove(paths, state->user_data);
  }
}

static void confirm_delete(SourceList *state, GPtrArray *paths) {
  if (!paths->len) return;
  GtkWindow *window = GTK_WINDOW(gtk_widget_get_root(state->root));
  gchar *title = paths->len == 1 ? g_strdup("Delete imported track?") : g_strdup_printf("Delete %u imported tracks?", paths->len);
  GtkWidget *dialog = adw_message_dialog_new(window, title,
    "The selected audio and its chapters will be removed from this project. Original files stay on disk.");
  gtk_window_set_destroy_with_parent(GTK_WINDOW(dialog), TRUE);
  g_free(title);
  adw_message_dialog_add_responses(ADW_MESSAGE_DIALOG(dialog), "cancel", "Cancel", "delete", paths->len == 1 ? "Delete Track" : "Delete Tracks", NULL);
  adw_message_dialog_set_response_appearance(ADW_MESSAGE_DIALOG(dialog), "delete", ADW_RESPONSE_DESTRUCTIVE);
  adw_message_dialog_set_default_response(ADW_MESSAGE_DIALOG(dialog), "cancel");
  adw_message_dialog_set_close_response(ADW_MESSAGE_DIALOG(dialog), "cancel");
  g_object_set_data_full(G_OBJECT(dialog), "source-paths", g_ptr_array_ref(paths), (GDestroyNotify)g_ptr_array_unref);
  g_signal_connect(dialog, "response", G_CALLBACK(deletion_response), state);
  gtk_window_present(GTK_WINDOW(dialog));
}

static void context_closed(GtkPopover *popover, gpointer user_data) {
  (void)user_data;
  gtk_widget_unparent(GTK_WIDGET(popover));
}

static void context_add(GtkButton *button, gpointer user_data) {
  SourceList *state = user_data;
  GtkWidget *popover = gtk_widget_get_ancestor(GTK_WIDGET(button), GTK_TYPE_POPOVER);
  gtk_popover_popdown(GTK_POPOVER(popover));
  state->add(state->user_data);
}

static void context_play(GtkButton *button, gpointer data) {
  SourceList *state = data;
  GtkWidget *popover = gtk_widget_get_ancestor(GTK_WIDGET(button), GTK_TYPE_POPOVER);
  gtk_popover_popdown(GTK_POPOVER(popover));
  play_button(state, selected_button(state), 1);
}

static void context_delete(GtkButton *button, gpointer user_data) {
  SourceList *state = user_data;
  GtkWidget *popover = gtk_widget_get_ancestor(GTK_WIDGET(button), GTK_TYPE_POPOVER);
  GPtrArray *paths = g_ptr_array_ref(g_object_get_data(G_OBJECT(popover), "source-paths"));
  gtk_popover_popdown(GTK_POPOVER(popover));
  confirm_delete(state, paths);
  g_ptr_array_unref(paths);
}

static void show_context(SourceList *state, double x, double y, gboolean include_selection) {
  GPtrArray *paths = include_selection ? selected_paths(state) : g_ptr_array_new_with_free_func(g_free);
  GtkWidget *popover = gtk_popover_new();
  gtk_widget_set_parent(popover, state->list);
  GdkRectangle point = {(int)x, (int)y, 1, 1};
  gtk_popover_set_pointing_to(GTK_POPOVER(popover), &point);
  GtkWidget *menu = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
  GtkWidget *add = gtk_button_new_with_label("Add Audio Files…");
  gtk_widget_set_tooltip_text(add, "Add WAV or AIFF recordings to this episode");
  gtk_widget_add_css_class(add, "flat");
  g_signal_connect(add, "clicked", G_CALLBACK(context_add), state);
  gtk_box_append(GTK_BOX(menu), add);
  if (paths->len) {
    GtkWidget *play = gtk_button_new_with_label("Play");
    gtk_widget_add_css_class(play, "flat");
    g_signal_connect(play, "clicked", G_CALLBACK(context_play), state);
    gtk_box_prepend(GTK_BOX(menu), play);
    GtkWidget *remove = gtk_button_new_with_label(paths->len == 1 ? "Delete Track…" : "Delete Tracks…");
    gtk_widget_set_tooltip_text(remove, "Remove selected imports and their chapters; original files stay on disk");
    gtk_widget_add_css_class(remove, "flat");
    g_signal_connect(remove, "clicked", G_CALLBACK(context_delete), state);
    gtk_box_append(GTK_BOX(menu), remove);
  }
  g_object_set_data_full(G_OBJECT(popover), "source-paths", paths, (GDestroyNotify)g_ptr_array_unref);
  gtk_popover_set_child(GTK_POPOVER(popover), menu);
  g_signal_connect(popover, "closed", G_CALLBACK(context_closed), NULL);
  gtk_popover_popup(GTK_POPOVER(popover));
}

static void right_clicked(GtkGestureClick *gesture, gint count, double x, double y, gpointer user_data) {
  (void)count;
  SourceList *state = user_data;
  GtkListBoxRow *row = gtk_list_box_get_row_at_y(GTK_LIST_BOX(state->list), (gint)y);
  if (row && !gtk_list_box_row_is_selected(row)) {
    gtk_list_box_unselect_all(GTK_LIST_BOX(state->list));
    gtk_list_box_select_row(GTK_LIST_BOX(state->list), row);
  }
  show_context(state, x, y, row != NULL);
  gtk_gesture_set_state(GTK_GESTURE(gesture), GTK_EVENT_SEQUENCE_CLAIMED);
}

static gboolean key_pressed(GtkEventControllerKey *controller, guint keyval, guint keycode, GdkModifierType modifiers, gpointer user_data) {
  (void)controller; (void)keycode;
  SourceList *state = user_data;
  if (modifiers & (GDK_CONTROL_MASK | GDK_ALT_MASK | GDK_SUPER_MASK)) return FALSE;
  guint key = gdk_keyval_to_lower(keyval);
  guint bit = key == GDK_KEY_j ? 1 : key == GDK_KEY_k ? 2 : key == GDK_KEY_l ? 4 : key == GDK_KEY_space ? 8 : 0;
  if (bit && !(modifiers & GDK_SHIFT_MASK)) {
    if (state->held_keys & bit) return TRUE;
    state->held_keys |= bit;
    GtkWidget *button = selected_button(state);
    if (!button) return TRUE;
    if (key == GDK_KEY_space) { state->slow = FALSE; playback_clicked(GTK_BUTTON(button), state); }
    else if (key == GDK_KEY_k) pause_playback(state);
    else {
      gboolean slow = (state->held_keys & 2) != 0;
      double current = state->active_button == button && state->playing ? state->rate : 0;
      play_button(state, button, encap_shuttle_rate(current, key == GDK_KEY_j ? -1 : 1, slow));
      state->slow = slow;
    }
    return TRUE;
  }
  if (keyval == GDK_KEY_AudioPlay) { GtkWidget *button = selected_button(state); if (button) playback_clicked(GTK_BUTTON(button), state); return TRUE; }
  if (keyval == GDK_KEY_AudioPause || keyval == GDK_KEY_AudioStop) { pause_playback(state); return TRUE; }
  if (keyval == GDK_KEY_Delete || keyval == GDK_KEY_BackSpace) {
    GPtrArray *paths = selected_paths(state);
    confirm_delete(state, paths);
    g_ptr_array_unref(paths);
    return TRUE;
  }
  if (keyval == GDK_KEY_Menu || (keyval == GDK_KEY_F10 && (modifiers & GDK_SHIFT_MASK))) {
    show_context(state, 12, 12, TRUE);
    return TRUE;
  }
  return FALSE;
}

static void key_released(GtkEventControllerKey *controller, guint keyval, guint keycode, GdkModifierType modifiers, gpointer data) {
  (void)controller; (void)keycode; (void)modifiers;
  SourceList *state = data;
  guint key = gdk_keyval_to_lower(keyval);
  guint bit = key == GDK_KEY_j ? 1 : key == GDK_KEY_k ? 2 : key == GDK_KEY_l ? 4 : key == GDK_KEY_space ? 8 : 0;
  state->held_keys &= ~bit;
  if (bit && state->slow) { state->slow = FALSE; pause_playback(state); }
}

static void focus_left(GtkEventControllerFocus *controller, gpointer data) {
  (void)controller;
  SourceList *state = data;
  state->held_keys = 0;
  if (state->slow) { state->slow = FALSE; pause_playback(state); }
}

GtkWidget *encap_source_list_new(EnCapAddSources add, EnCapRemoveSources remove, gpointer user_data) {
  SourceList *state = g_new0(SourceList, 1);
  state->waveforms = encap_waveforms_new();
  state->add = add; state->remove = remove; state->user_data = user_data;
  state->root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
  gtk_widget_set_size_request(state->root, 140, -1);
  GtkWidget *heading = gtk_label_new("Source Recordings");
  gtk_widget_set_halign(heading, GTK_ALIGN_START);
  gtk_widget_add_css_class(heading, "dim-label");
  gtk_box_append(GTK_BOX(state->root), heading);
  GtkWidget *scroll = gtk_scrolled_window_new();
  gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
  gtk_widget_set_vexpand(scroll, TRUE);
  state->list = gtk_list_box_new();
  gtk_list_box_set_activate_on_single_click(GTK_LIST_BOX(state->list), FALSE);
  g_signal_connect(state->list, "row-activated", G_CALLBACK(row_activated), state);
  gtk_list_box_set_selection_mode(GTK_LIST_BOX(state->list), GTK_SELECTION_MULTIPLE);
  gtk_widget_set_vexpand(state->list, TRUE);
  gtk_accessible_update_property(GTK_ACCESSIBLE(state->list), GTK_ACCESSIBLE_PROPERTY_LABEL, "Source recordings", -1);
  gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll), state->list);
  gtk_box_append(GTK_BOX(state->root), scroll);
  GtkGesture *context = gtk_gesture_click_new();
  gtk_gesture_single_set_button(GTK_GESTURE_SINGLE(context), GDK_BUTTON_SECONDARY);
  g_signal_connect(context, "pressed", G_CALLBACK(right_clicked), state);
  gtk_widget_add_controller(state->list, GTK_EVENT_CONTROLLER(context));
  GtkEventController *keys = gtk_event_controller_key_new();
  gtk_event_controller_set_propagation_phase(keys, GTK_PHASE_CAPTURE);
  g_signal_connect(keys, "key-released", G_CALLBACK(key_released), state);
  GtkEventController *focus = gtk_event_controller_focus_new();
  g_signal_connect(focus, "leave", G_CALLBACK(focus_left), state);
  gtk_widget_add_controller(state->list, focus);
  g_signal_connect(keys, "key-pressed", G_CALLBACK(key_pressed), state);
  gtk_widget_add_controller(state->list, keys);
  GtkCssProvider *css = gtk_css_provider_new();
  gtk_css_provider_load_from_data(css,
    ".source-waveform { opacity: 0.45; } .source-recording-row:selected .source-waveform { opacity: 1; }"
    ".source-recording-row .source-playback { opacity: 0.4; min-width: 24px; min-height: 28px; padding: 0; }"
    ".source-recording-row:hover .source-playback, .source-recording-row:selected .source-playback, "
    ".source-recording-row:focus-visible .source-playback, .source-playback:focus-visible { opacity: 1; }", -1);
  gtk_style_context_add_provider_for_display(gtk_widget_get_display(state->root), GTK_STYLE_PROVIDER(css), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
  g_object_unref(css);
  g_object_set_data_full(G_OBJECT(state->root), "source-state", state, free_source_list);
  return state->root;
}

gint encap_source_list_set_sources(GtkWidget *widget, JsonArray *sources) {
  SourceList *state = g_object_get_data(G_OBJECT(widget), "source-state");
  stop_playback(state);
  GtkListBoxRow *existing;
  while ((existing = gtk_list_box_get_row_at_index(GTK_LIST_BOX(state->list), 0)))
    gtk_list_box_remove(GTK_LIST_BOX(state->list), GTK_WIDGET(existing));
  gint shortest = G_MAXINT;
  for (guint i = 0; sources && i < json_array_get_length(sources); i++) {
    JsonObject *source = json_array_get_object_element(sources, i);
    const gchar *name = json_object_get_string_member_with_default(source, "display_name", "Audio");
    const gchar *path = json_object_get_string_member_with_default(source, "source_path", "");
    GtkWidget *row = gtk_list_box_row_new();
    gtk_widget_add_css_class(row, "source-recording-row");
    g_object_set_data_full(G_OBJECT(row), "source-path", g_strdup(path), g_free);
    GtkWidget *content = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    GtkWidget *detail = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
    gtk_widget_set_hexpand(detail, TRUE);
    GtkWidget *label = gtk_label_new(name);
    gtk_label_set_ellipsize(GTK_LABEL(label), PANGO_ELLIPSIZE_END);
    gtk_label_set_xalign(GTK_LABEL(label), 0);
    PangoLayout *layout = gtk_widget_create_pango_layout(label, name);
    gint width; pango_layout_get_pixel_size(layout, &width, NULL);
    shortest = MIN(shortest, width); g_object_unref(layout);
    gint seconds = (gint)json_object_get_double_member_with_default(source, "duration_seconds", 0);
    gchar *time = g_strdup_printf("%d:%02d", seconds / 60, seconds % 60);
    GtkWidget *duration = gtk_label_new(time); g_free(time);
    gtk_label_set_xalign(GTK_LABEL(duration), 1);
    gtk_widget_add_css_class(duration, "dim-label");
    gtk_widget_add_css_class(duration, "caption");
    const gchar *extension = strrchr(path, '.');
    gboolean is_wave = extension && (g_ascii_strcasecmp(extension, ".wav") == 0 || g_ascii_strcasecmp(extension, ".wave") == 0);
    gboolean is_aiff = extension && (g_ascii_strcasecmp(extension, ".aif") == 0 || g_ascii_strcasecmp(extension, ".aiff") == 0 || g_ascii_strcasecmp(extension, ".aifc") == 0);
    gchar *type_label = is_wave ? g_strdup("WAV") : is_aiff ? g_strdup("AIFF") : g_ascii_strup(extension ? extension + 1 : "", -1);
    GtkWidget *format = gtk_label_new(type_label);
    g_free(type_label);
    gtk_widget_add_css_class(format, "dim-label");
    gtk_widget_add_css_class(format, "caption");
    gtk_label_set_xalign(GTK_LABEL(format), 0);
    gtk_widget_set_hexpand(format, FALSE);
    GtkWidget *metadata = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_box_append(GTK_BOX(metadata), format);
    gtk_box_append(GTK_BOX(metadata), encap_waveform_new(state->waveforms, path));
    gtk_box_append(GTK_BOX(metadata), duration);
    gtk_box_append(GTK_BOX(detail), label); gtk_box_append(GTK_BOX(detail), metadata);
    gtk_box_append(GTK_BOX(content), detail);
    GtkWidget *button = gtk_button_new_from_icon_name("media-playback-start-symbolic");
    gtk_widget_add_css_class(button, "flat"); gtk_widget_add_css_class(button, "source-playback");
    gtk_widget_set_valign(button, GTK_ALIGN_CENTER);
    g_object_set_data_full(G_OBJECT(button), "source-path", g_strdup(path), g_free);
    g_object_set_data_full(G_OBJECT(button), "source-name", g_strdup(name), g_free);
    g_object_set_data(G_OBJECT(row), "playback-button", button);
    g_object_set_data_full(G_OBJECT(button), "source-duration", g_strdup_printf("%.6f", json_object_get_double_member_with_default(source, "duration_seconds", 0)), g_free);
    update_button(button, FALSE);
    g_signal_connect(button, "clicked", G_CALLBACK(playback_clicked), state);
    gtk_box_append(GTK_BOX(content), button);
    gtk_list_box_row_set_child(GTK_LIST_BOX_ROW(row), content);
    gtk_list_box_append(GTK_LIST_BOX(state->list), row);
  }
  return MAX(180, (shortest == G_MAXINT ? 140 : shortest) + 48);
}

/* MPRIS is the standard desktop media session on GNOME, KDE, and other Linux desktops. */
static const gchar *media_path = "/org/mpris/MediaPlayer2";
static const gchar *media_player_interface = "org.mpris.MediaPlayer2.Player";
static const gchar *media_xml =
  "<node><interface name='org.mpris.MediaPlayer2'>"
  "<method name='Raise'/><method name='Quit'/>"
  "<property name='CanQuit' type='b' access='read'/><property name='CanRaise' type='b' access='read'/>"
  "<property name='HasTrackList' type='b' access='read'/><property name='Identity' type='s' access='read'/>"
  "<property name='DesktopEntry' type='s' access='read'/><property name='SupportedUriSchemes' type='as' access='read'/>"
  "<property name='SupportedMimeTypes' type='as' access='read'/></interface>"
  "<interface name='org.mpris.MediaPlayer2.Player'>"
  "<method name='Next'/><method name='Previous'/><method name='Pause'/><method name='PlayPause'/><method name='Stop'/><method name='Play'/>"
  "<method name='Seek'><arg type='x' direction='in' name='Offset'/></method>"
  "<method name='SetPosition'><arg type='o' direction='in' name='TrackId'/><arg type='x' direction='in' name='Position'/></method>"
  "<method name='OpenUri'><arg type='s' direction='in' name='Uri'/></method>"
  "<signal name='Seeked'><arg type='x' name='Position'/></signal>"
  "<property name='PlaybackStatus' type='s' access='read'/><property name='Rate' type='d' access='readwrite'/>"
  "<property name='Metadata' type='a{sv}' access='read'/><property name='Volume' type='d' access='readwrite'/>"
  "<property name='Position' type='x' access='read'/><property name='MinimumRate' type='d' access='read'/>"
  "<property name='MaximumRate' type='d' access='read'/><property name='CanGoNext' type='b' access='read'/>"
  "<property name='CanGoPrevious' type='b' access='read'/><property name='CanPlay' type='b' access='read'/>"
  "<property name='CanPause' type='b' access='read'/><property name='CanSeek' type='b' access='read'/>"
  "<property name='CanControl' type='b' access='read'/></interface></node>";

static GtkListBoxRow *media_active_row(SourceList *state) {
  return state->active_button ? GTK_LIST_BOX_ROW(gtk_widget_get_ancestor(state->active_button, GTK_TYPE_LIST_BOX_ROW)) : NULL;
}

static GtkListBoxRow *media_adjacent(SourceList *state, gint direction) {
  GtkListBoxRow *row = media_active_row(state);
  gint index = row ? gtk_list_box_row_get_index(row) + direction : -1;
  return index < 0 ? NULL : gtk_list_box_get_row_at_index(GTK_LIST_BOX(state->list), index);
}

static gchar *media_track_id(SourceList *state) {
  if (!state->active_path) return g_strdup("/org/mpris/MediaPlayer2/TrackList/NoTrack");
  gchar *hash = g_compute_checksum_for_string(G_CHECKSUM_SHA256, state->active_path, -1);
  gchar *id = g_strconcat("/org/mpris/MediaPlayer2/track_", hash, NULL); g_free(hash); return id;
}

static gint64 media_duration(SourceList *state) {
  const gchar *duration = state->active_button ? g_object_get_data(G_OBJECT(state->active_button), "source-duration") : NULL;
  return duration ? (gint64)(g_ascii_strtod(duration, NULL) * G_USEC_PER_SEC) : 0;
}

static GVariant *media_property(GDBusConnection *connection, const gchar *sender, const gchar *path,
    const gchar *interface, const gchar *property, GError **error, gpointer data) {
  (void)connection; (void)sender; (void)path; (void)interface;
  SourceList *state = data;
  if (g_str_equal(property, "Identity")) return g_variant_new_string("EnCap");
  if (g_str_equal(property, "DesktopEntry")) return g_variant_new_string("com.tlolabs.encap");
  if (g_str_equal(property, "CanQuit") || g_str_equal(property, "HasTrackList")) return g_variant_new_boolean(FALSE);
  if (g_str_equal(property, "CanRaise") || g_str_equal(property, "CanControl")) return g_variant_new_boolean(TRUE);
  if (g_str_equal(property, "SupportedUriSchemes") || g_str_equal(property, "SupportedMimeTypes")) return g_variant_new_strv(NULL, 0);
  if (g_str_equal(property, "PlaybackStatus")) return g_variant_new_string(!state->player ? "Stopped" : state->playing ? "Playing" : "Paused");
  if (g_str_equal(property, "Rate")) return g_variant_new_double(state->rate ? state->rate : 1);
  if (g_str_equal(property, "MinimumRate")) return g_variant_new_double(-32);
  if (g_str_equal(property, "MaximumRate")) return g_variant_new_double(32);
  if (g_str_equal(property, "Position")) return g_variant_new_int64(playback_position(state) / GST_USECOND);
  if (g_str_equal(property, "Volume")) {
    double volume = 1; if (state->player) g_object_get(state->player, "volume", &volume, NULL);
    return g_variant_new_double(volume);
  }
  if (g_str_equal(property, "CanGoNext")) return g_variant_new_boolean(media_adjacent(state, 1) != NULL);
  if (g_str_equal(property, "CanGoPrevious")) return g_variant_new_boolean(media_adjacent(state, -1) != NULL);
  if (g_str_equal(property, "CanPlay")) return g_variant_new_boolean(state->active_button != NULL);
  if (g_str_equal(property, "CanPause") || g_str_equal(property, "CanSeek")) return g_variant_new_boolean(state->player && state->ready);
  if (g_str_equal(property, "Metadata")) {
    GVariantBuilder metadata; g_variant_builder_init(&metadata, G_VARIANT_TYPE("a{sv}"));
    gchar *id = media_track_id(state);
    g_variant_builder_add(&metadata, "{sv}", "mpris:trackid", g_variant_new_object_path(id)); g_free(id);
    if (state->active_button) {
      const gchar *title = g_object_get_data(G_OBJECT(state->active_button), "source-name");
      g_variant_builder_add(&metadata, "{sv}", "xesam:title", g_variant_new_string(title ? title : "Recording"));
      g_variant_builder_add(&metadata, "{sv}", "mpris:length", g_variant_new_int64(media_duration(state)));
    }
    return g_variant_builder_end(&metadata);
  }
  g_set_error(error, G_DBUS_ERROR, G_DBUS_ERROR_UNKNOWN_PROPERTY, "Unknown property: %s", property);
  return NULL;
}

static void media_update(SourceList *state) {
  if (!state->media_bus || !state->media_registration[1]) return;
  GVariantBuilder changed; g_variant_builder_init(&changed, G_VARIANT_TYPE("a{sv}"));
  const gchar *properties[] = {"PlaybackStatus", "Rate", "Metadata", "CanGoNext", "CanGoPrevious", "CanPlay", "CanPause", "CanSeek", "Volume", NULL};
  for (guint i = 0; properties[i]; i++)
    g_variant_builder_add(&changed, "{sv}", properties[i], media_property(NULL, NULL, NULL, NULL, properties[i], NULL, state));
  g_dbus_connection_emit_signal(state->media_bus, NULL, media_path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
    g_variant_new("(sa{sv}as)", media_player_interface, &changed, NULL), NULL);
}

static void media_method(GDBusConnection *connection, const gchar *sender, const gchar *path,
    const gchar *interface, const gchar *method, GVariant *parameters, GDBusMethodInvocation *invocation, gpointer data) {
  (void)connection; (void)sender; (void)path; (void)interface;
  SourceList *state = data;
  if (!gtk_widget_is_sensitive(state->root)) {
    g_dbus_method_invocation_return_error(invocation, G_DBUS_ERROR, G_DBUS_ERROR_FAILED, "The project is busy."); return;
  }
  GtkWidget *button = state->active_button;
  if (g_str_equal(method, "Raise")) {
    GtkRoot *root = gtk_widget_get_root(state->root);
    if (GTK_IS_WINDOW(root)) gtk_window_present(GTK_WINDOW(root));
  } else if (g_str_equal(method, "Play")) play_button(state, button, 1);
  else if (g_str_equal(method, "PlayPause")) { if (button) playback_clicked(GTK_BUTTON(button), state); }
  else if (g_str_equal(method, "Pause")) pause_playback(state);
  else if (g_str_equal(method, "Stop")) {
    pause_playback(state); seek_playback(state, 0, 1); state->rate = 1;
  } else if (g_str_equal(method, "Next") || g_str_equal(method, "Previous")) {
    GtkListBoxRow *row = media_adjacent(state, g_str_equal(method, "Next") ? 1 : -1);
    if (row) {
      gtk_list_box_unselect_all(GTK_LIST_BOX(state->list)); gtk_list_box_select_row(GTK_LIST_BOX(state->list), row);
      play_button(state, g_object_get_data(G_OBJECT(row), "playback-button"), 1);
    }
  } else if (g_str_equal(method, "Seek") || g_str_equal(method, "SetPosition")) {
    gint64 position;
    if (g_str_equal(method, "Seek")) {
      gint64 offset; g_variant_get(parameters, "(x)", &offset);
      double requested = (double)(playback_position(state) / GST_USECOND) + offset;
      position = (gint64)CLAMP(requested, 0, (double)media_duration(state));
    } else {
      const gchar *id; g_variant_get(parameters, "(&ox)", &id, &position);
      gchar *current = media_track_id(state);
      gboolean matches = g_str_equal(id, current); g_free(current);
      if (!matches || position < 0 || position > media_duration(state)) {
        g_dbus_method_invocation_return_value(invocation, NULL); return;
      }
    }
    if (seek_playback(state, position * GST_USECOND, state->rate))
      g_dbus_connection_emit_signal(state->media_bus, NULL, media_path, media_player_interface, "Seeked", g_variant_new("(x)", position), NULL);
  } else {
    g_dbus_method_invocation_return_error(invocation, G_DBUS_ERROR, G_DBUS_ERROR_NOT_SUPPORTED, "This media action is unavailable."); return;
  }
  media_update(state);
  g_dbus_method_invocation_return_value(invocation, NULL);
}

static gboolean media_set_property(GDBusConnection *connection, const gchar *sender, const gchar *path,
    const gchar *interface, const gchar *property, GVariant *value, GError **error, gpointer data) {
  (void)connection; (void)sender; (void)path; (void)interface;
  SourceList *state = data;
  double number = g_variant_get_double(value);
  if (g_str_equal(property, "Volume") && number >= 0 && number <= 1 && state->player) {
    g_object_set(state->player, "volume", number, NULL); media_update(state); return TRUE;
  }
  if (g_str_equal(property, "Rate") && number >= -32 && number <= 32 && state->player) {
    if (number == 0) { pause_playback(state); return TRUE; }
    if (seek_playback(state, playback_position(state), number)) { state->rate = number; media_update(state); return TRUE; }
  }
  g_set_error(error, G_DBUS_ERROR, G_DBUS_ERROR_NOT_SUPPORTED, "The decoder does not support this value."); return FALSE;
}

static const GDBusInterfaceVTable media_vtable = { .method_call = media_method, .get_property = media_property, .set_property = media_set_property };

static void media_bus_acquired(GDBusConnection *connection, const gchar *name, gpointer data) {
  (void)name;
  SourceList *state = data;
  g_set_object(&state->media_bus, connection);
  for (guint i = 0; i < 2; i++)
    state->media_registration[i] = g_dbus_connection_register_object(connection, media_path, state->media_info->interfaces[i], &media_vtable, state, NULL, NULL);
  media_update(state);
}

static void media_start(SourceList *state) {
  if (state->media_owner) return;
  state->media_info = g_dbus_node_info_new_for_xml(media_xml, NULL);
  if (!state->media_info) return;
  gchar *name = g_strdup_printf("org.mpris.MediaPlayer2.encap.instance%u", (guint)getpid());
  state->media_owner = g_bus_own_name(G_BUS_TYPE_SESSION, name, G_BUS_NAME_OWNER_FLAGS_NONE, media_bus_acquired, NULL, NULL, state, NULL);
  g_free(name);
}

static void media_free(SourceList *state) {
  if (state->media_owner) g_bus_unown_name(state->media_owner);
  for (guint i = 0; i < 2; i++)
    if (state->media_bus && state->media_registration[i]) g_dbus_connection_unregister_object(state->media_bus, state->media_registration[i]);
  g_clear_object(&state->media_bus);
  g_clear_pointer(&state->media_info, g_dbus_node_info_unref);
}
