#include <adwaita.h>
#include <json-glib/json-glib.h>
#include <glib/gstdio.h>
#include <fcntl.h>
#include <unistd.h>

typedef struct {
  AdwApplication *application;
  AdwApplicationWindow *window;
  GtkWidget *podcast_title;
  GtkWidget *episode_title;
  GtkWidget *summary;
  GtkWidget *chapters;
  GtkWidget *transcript;
  GtkWidget *provider;
  GtkWidget *status;
  GtkWidget *cancel;
  JsonNode *project;
  GPtrArray *provider_ids;
  GSubprocess *process;
  gchar *payload_path;
  gchar *operation;
  gchar *pending_open;
  guint recovery_source;
  gboolean presenting_project;
} AppState;

static void run_engine(AppState *state, const gchar *operation, const gchar *arg1, const gchar *arg2);
static gboolean write_payload(AppState *state);
static void schedule_recovery(AppState *state);

static gchar *engine_path(void) {
  gchar *binary = g_file_read_link("/proc/self/exe", NULL);
  if (!binary) return g_strdup("encap-engine");
  gchar *directory = g_path_get_dirname(binary);
  gchar *engine = g_build_filename(directory, "encap-engine", NULL);
  g_free(binary);
  g_free(directory);
  return engine;
}

static void set_status(AppState *state, const gchar *message, gboolean error) {
  gtk_label_set_text(GTK_LABEL(state->status), message);
  gtk_widget_remove_css_class(state->status, error ? "success" : "error");
  gtk_widget_add_css_class(state->status, error ? "error" : "dim-label");
}

static void present_project(AppState *state) {
  state->presenting_project = TRUE;
  JsonObject *root = json_node_get_object(state->project);
  JsonObject *metadata = json_object_get_object_member(root, "metadata");
  gtk_editable_set_text(GTK_EDITABLE(state->podcast_title), json_object_get_string_member_with_default(metadata, "podcast_title", ""));
  gtk_editable_set_text(GTK_EDITABLE(state->episode_title), json_object_get_string_member_with_default(metadata, "episode_title", ""));
  GtkTextBuffer *summary = gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->summary));
  gtk_text_buffer_set_text(summary, json_object_get_string_member_with_default(metadata, "summary", ""), -1);

  GtkTextBuffer *chapters = gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->chapters));
  GString *lines = g_string_new(NULL);
  JsonArray *array = json_object_get_array_member(root, "chapters");
  for (guint i = 0; array && i < json_array_get_length(array); i++) {
    JsonObject *chapter = json_array_get_object_element(array, i);
    g_string_append_printf(lines, "%u. %s\n", i + 1, json_object_get_string_member_with_default(chapter, "title", "Untitled"));
  }
  gtk_text_buffer_set_text(chapters, lines->str, -1);
  g_string_free(lines, TRUE);
  state->presenting_project = FALSE;
  set_status(state, "Project loaded.", FALSE);
}

static void present_transcript(AppState *state, JsonNode *node) {
  JsonArray *array = json_node_get_array(node);
  GString *text = g_string_new(NULL);
  for (guint i = 0; array && i < json_array_get_length(array); i++) {
    JsonObject *segment = json_array_get_object_element(array, i);
    const gchar *speaker = json_object_get_string_member_with_default(segment, "speaker", "");
    if (*speaker) g_string_append_printf(text, "%s: ", speaker);
    g_string_append_printf(text, "%s\n\n", json_object_get_string_member_with_default(segment, "text", ""));
  }
  gtk_text_buffer_set_text(gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->transcript)), text->str, -1);
  g_string_free(text, TRUE);
}

static void model_action_clicked(GtkButton *button, gpointer user_data) {
  AppState *state = user_data;
  const gchar *operation = g_object_get_data(G_OBJECT(button), "operation");
  const gchar *model_id = g_object_get_data(G_OBJECT(button), "model-id");
  GtkWidget *window = gtk_widget_get_ancestor(GTK_WIDGET(button), GTK_TYPE_WINDOW);
  if (window) gtk_window_destroy(GTK_WINDOW(window));
  run_engine(state, operation, model_id, NULL);
}

static void present_models(AppState *state, JsonArray *models) {
  GtkWidget *window = gtk_window_new();
  gtk_window_set_title(GTK_WINDOW(window), "Local Transcription Models");
  gtk_window_set_transient_for(GTK_WINDOW(window), GTK_WINDOW(state->window));
  gtk_window_set_modal(GTK_WINDOW(window), TRUE);
  gtk_window_set_default_size(GTK_WINDOW(window), 640, 440);
  GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  gtk_widget_set_margin_start(box, 18); gtk_widget_set_margin_end(box, 18);
  gtk_widget_set_margin_top(box, 18); gtk_widget_set_margin_bottom(box, 18);
  GtkWidget *intro = gtk_label_new("Models come from EnCap's pinned catalog, are SHA-256 verified, and run locally.");
  gtk_label_set_wrap(GTK_LABEL(intro), TRUE);
  gtk_widget_set_halign(intro, GTK_ALIGN_START);
  gtk_box_append(GTK_BOX(box), intro);
  GtkWidget *list = gtk_list_box_new();
  for (guint i = 0; models && i < json_array_get_length(models); i++) {
    JsonObject *model = json_array_get_object_element(models, i);
    gboolean installed = json_object_get_boolean_member_with_default(model, "installed", FALSE);
    gboolean download_allowed = json_object_get_boolean_member_with_default(model, "download_allowed", TRUE);
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    GtkWidget *detail = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
    gtk_widget_set_hexpand(detail, TRUE);
    GtkWidget *name = gtk_label_new(json_object_get_string_member_with_default(model, "name", "Whisper model"));
    gtk_widget_add_css_class(name, "heading"); gtk_widget_set_halign(name, GTK_ALIGN_START);
    gchar *subtitle_text = g_strdup_printf("%s · %s\n%s",
      json_object_get_string_member_with_default(model, "download_size", ""),
      json_object_get_string_member_with_default(model, "languages", ""),
      json_object_get_string_member_with_default(model, "description", ""));
    GtkWidget *subtitle = gtk_label_new(subtitle_text); g_free(subtitle_text);
    gtk_label_set_wrap(GTK_LABEL(subtitle), TRUE); gtk_widget_set_halign(subtitle, GTK_ALIGN_START);
    gtk_widget_add_css_class(subtitle, "dim-label");
    gtk_box_append(GTK_BOX(detail), name); gtk_box_append(GTK_BOX(detail), subtitle);
    GtkWidget *action = gtk_button_new_with_label(installed ? "Remove" : "Download");
    gtk_widget_set_sensitive(action, installed || download_allowed);
    if (!installed && !download_allowed)
      gtk_widget_set_tooltip_text(action, "EnCap is reusing a compatible model already installed by another app.");
    g_object_set_data_full(G_OBJECT(action), "operation", g_strdup(installed ? "remove-model" : "install-model"), g_free);
    g_object_set_data_full(G_OBJECT(action), "model-id", g_strdup(json_object_get_string_member_with_default(model, "id", "")), g_free);
    g_signal_connect(action, "clicked", G_CALLBACK(model_action_clicked), state);
    gtk_box_append(GTK_BOX(row), detail); gtk_box_append(GTK_BOX(row), action);
    gtk_list_box_append(GTK_LIST_BOX(list), row);
  }
  GtkWidget *scroll = gtk_scrolled_window_new();
  gtk_widget_set_vexpand(scroll, TRUE);
  gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll), list);
  gtk_box_append(GTK_BOX(box), scroll);
  gtk_window_set_child(GTK_WINDOW(window), box);
  gtk_window_present(GTK_WINDOW(window));
}

static gchar *buffer_text(GtkWidget *view) {
  GtkTextIter start, end;
  GtkTextBuffer *buffer = gtk_text_view_get_buffer(GTK_TEXT_VIEW(view));
  gtk_text_buffer_get_bounds(buffer, &start, &end);
  return gtk_text_buffer_get_text(buffer, &start, &end, FALSE);
}

static void sync_text_edits(AppState *state, JsonObject *root) {
  JsonArray *chapters = json_object_get_array_member(root, "chapters");
  gchar *chapter_text = buffer_text(state->chapters);
  gchar **chapter_lines = g_strsplit(chapter_text, "\n", -1);
  for (guint i = 0; chapters && i < json_array_get_length(chapters) && chapter_lines[i]; i++) {
    gchar *title = g_strstr_len(chapter_lines[i], -1, ". ");
    json_object_set_string_member(json_array_get_object_element(chapters, i), "title", title ? title + 2 : chapter_lines[i]);
  }
  g_strfreev(chapter_lines);
  g_free(chapter_text);

  JsonArray *segments = json_object_get_array_member(root, "transcript_segments");
  gchar *transcript_text = buffer_text(state->transcript);
  gchar **paragraphs = g_strsplit(transcript_text, "\n\n", -1);
  for (guint i = 0; segments && i < json_array_get_length(segments) && paragraphs[i]; i++) {
    JsonObject *segment = json_array_get_object_element(segments, i);
    gchar *separator = g_strstr_len(paragraphs[i], -1, ": ");
    if (separator) {
      *separator = '\0';
      json_object_set_string_member(segment, "speaker", paragraphs[i]);
      json_object_set_string_member(segment, "text", separator + 2);
    } else {
      json_object_set_string_member(segment, "text", paragraphs[i]);
    }
  }
  g_strfreev(paragraphs);
  g_free(transcript_text);
}

static void engine_done(GObject *source, GAsyncResult *result, gpointer user_data) {
  AppState *state = user_data;
  gboolean refresh_providers = state->operation &&
    (g_str_equal(state->operation, "install-model") || g_str_equal(state->operation, "remove-model") || g_str_equal(state->operation, "load-recovery"));
  gboolean clear_recovery = state->operation &&
    (g_str_equal(state->operation, "save") || g_str_equal(state->operation, "open"));
  gchar *stdout_text = NULL, *stderr_text = NULL;
  GError *error = NULL;
  gboolean communicated = g_subprocess_communicate_utf8_finish(G_SUBPROCESS(source), result, &stdout_text, &stderr_text, &error);
  gboolean success = communicated && g_subprocess_get_successful(G_SUBPROCESS(source));
  if (!success) {
    const gchar *message = error ? error->message : (stderr_text && *stderr_text ? stderr_text : "The EnCap engine failed.");
    JsonParser *failure = json_parser_new();
    if (stdout_text && json_parser_load_from_data(failure, stdout_text, -1, NULL)) {
      JsonObject *object = json_node_get_object(json_parser_get_root(failure));
      message = json_object_get_string_member_with_default(object, "error", message);
    }
    set_status(state, message, TRUE);
    g_object_unref(failure);
  } else {
    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, stdout_text, -1, &error)) {
      set_status(state, "The EnCap engine returned an invalid response.", TRUE);
    } else if (g_str_equal(state->operation, "inspect") || g_str_equal(state->operation, "open")) {
      if (state->project) json_node_unref(state->project);
      state->project = json_node_copy(json_parser_get_root(parser));
      present_project(state);
      if (g_str_equal(state->operation, "inspect")) schedule_recovery(state);
    } else if (g_str_equal(state->operation, "load-recovery")) {
      JsonObject *response = json_node_get_object(json_parser_get_root(parser));
      JsonNode *recovered = json_object_get_member(response, "project");
      if (recovered && !JSON_NODE_HOLDS_NULL(recovered)) {
        if (state->project) json_node_unref(state->project);
        state->project = json_node_copy(recovered);
        present_project(state);
        set_status(state, "Recovered unsaved work from the previous session.", FALSE);
      }
    } else if (g_str_equal(state->operation, "providers")) {
      JsonArray *providers = json_node_get_array(json_parser_get_root(parser));
      GtkStringList *names = gtk_string_list_new(NULL);
      g_ptr_array_set_size(state->provider_ids, 0);
      for (guint i = 0; providers && i < json_array_get_length(providers); i++) {
        JsonObject *provider = json_array_get_object_element(providers, i);
        gtk_string_list_append(names, json_object_get_string_member_with_default(provider, "name", "Local model"));
        g_ptr_array_add(state->provider_ids, g_strdup(json_object_get_string_member_with_default(provider, "id", "")));
      }
      gtk_drop_down_set_model(GTK_DROP_DOWN(state->provider), G_LIST_MODEL(names));
      g_object_unref(names);
      set_status(state, "Local transcription engines loaded.", FALSE);
    } else if (g_str_equal(state->operation, "models")) {
      present_models(state, json_node_get_array(json_parser_get_root(parser)));
      set_status(state, "Transcription model catalog loaded.", FALSE);
    } else if (g_str_equal(state->operation, "install-model") || g_str_equal(state->operation, "remove-model")) {
      set_status(state, g_str_equal(state->operation, "install-model") ? "Transcription model installed." : "Transcription model removed.", FALSE);
    } else if (g_str_equal(state->operation, "transcribe")) {
      JsonArray *segments = json_node_get_array(json_parser_get_root(parser));
      if (state->project && segments) {
        json_object_set_array_member(json_node_get_object(state->project), "transcript_segments", json_array_ref(segments));
      }
      present_transcript(state, json_parser_get_root(parser));
      set_status(state, "Transcription complete.", FALSE);
      schedule_recovery(state);
    } else if (g_str_equal(state->operation, "save-recovery")) {
      set_status(state, "Unsaved changes protected for crash recovery.", FALSE);
    } else if (g_str_equal(state->operation, "clear-recovery")) {
      set_status(state, "Project ready.", FALSE);
    } else {
      set_status(state, g_str_equal(state->operation, "save") ? "Project saved." : "Audio exported.", FALSE);
    }
    g_object_unref(parser);
  }
  if (error) g_error_free(error);
  g_free(stdout_text); g_free(stderr_text);
  g_clear_object(&state->process);
  gtk_widget_set_visible(state->cancel, FALSE);
  if (state->payload_path) { g_unlink(state->payload_path); g_clear_pointer(&state->payload_path, g_free); }
  if (state->pending_open) {
    gchar *path = g_steal_pointer(&state->pending_open);
    run_engine(state, "open", path, NULL);
    g_free(path);
  } else if (refresh_providers) run_engine(state, "providers", NULL, NULL);
  else if (clear_recovery) run_engine(state, "clear-recovery", NULL, NULL);
}

static void run_engine(AppState *state, const gchar *operation, const gchar *arg1, const gchar *arg2) {
  if (state->process) return;
  gchar *engine = engine_path();
  const gchar *argv[] = { engine, operation, arg1, arg2, NULL };
  GError *error = NULL;
  state->process = g_subprocess_newv(argv, G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_PIPE, &error);
  g_free(engine);
  if (!state->process) { set_status(state, error->message, TRUE); g_error_free(error); return; }
  g_free(state->operation); state->operation = g_strdup(operation);
  gtk_widget_set_visible(state->cancel, TRUE);
  set_status(state, "Working…", FALSE);
  g_subprocess_communicate_utf8_async(state->process, NULL, NULL, engine_done, state);
}

static gboolean write_payload(AppState *state) {
  if (!state->project) { set_status(state, "Import audio or open a project first.", TRUE); return FALSE; }
  JsonObject *root = json_node_get_object(state->project);
  JsonObject *metadata = json_object_get_object_member(root, "metadata");
  json_object_set_string_member(metadata, "podcast_title", gtk_editable_get_text(GTK_EDITABLE(state->podcast_title)));
  json_object_set_string_member(metadata, "episode_title", gtk_editable_get_text(GTK_EDITABLE(state->episode_title)));
  GtkTextIter start, end;
  GtkTextBuffer *buffer = gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->summary));
  gtk_text_buffer_get_bounds(buffer, &start, &end);
  gchar *summary = gtk_text_buffer_get_text(buffer, &start, &end, FALSE);
  json_object_set_string_member(metadata, "summary", summary);
  g_free(summary);
  sync_text_edits(state, root);
  GError *error = NULL;
  gint descriptor = g_file_open_tmp("encap-payload-XXXXXX.json", &state->payload_path, &error);
  if (descriptor < 0) { set_status(state, error->message, TRUE); g_error_free(error); return FALSE; }
  close(descriptor);
  JsonGenerator *generator = json_generator_new();
  json_generator_set_root(generator, state->project);
  gboolean saved = json_generator_to_file(generator, state->payload_path, &error);
  g_object_unref(generator);
  if (!saved) { set_status(state, error->message, TRUE); g_error_free(error); return FALSE; }
  return TRUE;
}

static gboolean save_recovery_timeout(gpointer user_data) {
  AppState *state = user_data;
  if (state->process) return G_SOURCE_CONTINUE;
  state->recovery_source = 0;
  if (state->project && write_payload(state))
    run_engine(state, "save-recovery", state->payload_path, NULL);
  return G_SOURCE_REMOVE;
}

static void schedule_recovery(AppState *state) {
  if (state->presenting_project || !state->project) return;
  if (state->recovery_source) g_source_remove(state->recovery_source);
  state->recovery_source = g_timeout_add(1000, save_recovery_timeout, state);
}

static void edit_changed(GtkWidget *widget, gpointer user_data) {
  schedule_recovery(user_data);
}

static void chooser_response(GtkNativeDialog *dialog, gint response, gpointer user_data) {
  AppState *state = user_data;
  if (response == GTK_RESPONSE_ACCEPT) {
    GFile *file = gtk_file_chooser_get_file(GTK_FILE_CHOOSER(dialog));
    gchar *path = g_file_get_path(file);
    const gchar *operation = g_object_get_data(G_OBJECT(dialog), "operation");
    if (g_str_equal(operation, "inspect") || g_str_equal(operation, "open")) run_engine(state, operation, path, NULL);
    else if (write_payload(state)) run_engine(state, operation, state->payload_path, path);
    g_free(path); g_object_unref(file);
  }
  g_object_unref(dialog);
}

static void choose(AppState *state, const gchar *operation) {
  gboolean folder = g_str_equal(operation, "inspect");
  gboolean output = g_str_equal(operation, "save") || g_str_equal(operation, "export");
  GtkFileChooserNative *chooser = gtk_file_chooser_native_new(
    output ? "Choose Destination" : "Open", GTK_WINDOW(state->window),
    output ? GTK_FILE_CHOOSER_ACTION_SAVE : (folder ? GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER : GTK_FILE_CHOOSER_ACTION_OPEN),
    output ? "Save" : "Open", "Cancel");
  g_object_set_data_full(G_OBJECT(chooser), "operation", g_strdup(operation), g_free);
  g_signal_connect(chooser, "response", G_CALLBACK(chooser_response), state);
  gtk_native_dialog_show(GTK_NATIVE_DIALOG(chooser));
}

static void choose_clicked(GtkButton *button, gpointer user_data) {
  AppState *state = user_data;
  choose(state, g_object_get_data(G_OBJECT(button), "operation"));
}

static void cancel_clicked(GtkButton *button, gpointer user_data) {
  AppState *state = user_data;
  if (state->process) g_subprocess_force_exit(state->process);
}

static void transcribe_clicked(GtkButton *button, gpointer user_data) {
  AppState *state = user_data;
  guint selected = gtk_drop_down_get_selected(GTK_DROP_DOWN(state->provider));
  if (selected >= state->provider_ids->len || !write_payload(state)) return;
  run_engine(state, "transcribe", state->payload_path, g_ptr_array_index(state->provider_ids, selected));
}

static void models_clicked(GtkButton *button, gpointer user_data) {
  run_engine(user_data, "models", NULL, NULL);
}

static GtkWidget *labeled_entry(const gchar *label, GtkWidget **entry) {
  GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
  GtkWidget *title = gtk_label_new(label);
  gtk_widget_set_halign(title, GTK_ALIGN_START);
  gtk_widget_add_css_class(title, "heading");
  *entry = gtk_entry_new();
  gtk_accessible_update_property(GTK_ACCESSIBLE(*entry), GTK_ACCESSIBLE_PROPERTY_LABEL, label, -1);
  gtk_box_append(GTK_BOX(box), title); gtk_box_append(GTK_BOX(box), *entry);
  return box;
}

static void activate(GApplication *application, gpointer user_data) {
  AppState *state = user_data;
  state->window = ADW_APPLICATION_WINDOW(adw_application_window_new(state->application));
  gtk_window_set_title(GTK_WINDOW(state->window), "EnCap");
  gtk_window_set_default_size(GTK_WINDOW(state->window), 1100, 760);
  GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
  GtkWidget *header = adw_header_bar_new();
  GtkWidget *stack = gtk_stack_new();
  GtkWidget *switcher = adw_view_switcher_new();
  adw_view_switcher_set_stack(ADW_VIEW_SWITCHER(switcher), GTK_STACK(stack));
  adw_header_bar_set_title_widget(ADW_HEADER_BAR(header), switcher);
  const gchar *buttons[][2] = {{"Import", "inspect"}, {"Open", "open"}, {"Save", "save"}, {"Export", "export"}};
  for (guint i = 0; i < 4; i++) {
    GtkWidget *button = gtk_button_new_with_label(buttons[i][0]);
    g_object_set_data_full(G_OBJECT(button), "operation", g_strdup(buttons[i][1]), g_free);
    g_signal_connect(button, "clicked", G_CALLBACK(choose_clicked), state);
    if (i < 2) adw_header_bar_pack_start(ADW_HEADER_BAR(header), button); else adw_header_bar_pack_end(ADW_HEADER_BAR(header), button);
  }
  GtkWidget *assemble = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  gtk_widget_set_margin_start(assemble, 24); gtk_widget_set_margin_end(assemble, 24); gtk_widget_set_margin_top(assemble, 24); gtk_widget_set_margin_bottom(assemble, 24);
  gtk_box_append(GTK_BOX(assemble), labeled_entry("Podcast title", &state->podcast_title));
  gtk_box_append(GTK_BOX(assemble), labeled_entry("Episode title", &state->episode_title));
  state->summary = gtk_text_view_new(); gtk_widget_set_size_request(state->summary, -1, 100); gtk_box_append(GTK_BOX(assemble), state->summary);
  state->chapters = gtk_text_view_new(); gtk_text_view_set_editable(GTK_TEXT_VIEW(state->chapters), TRUE); gtk_accessible_update_property(GTK_ACCESSIBLE(state->chapters), GTK_ACCESSIBLE_PROPERTY_LABEL, "Editable chapter titles", -1); gtk_widget_set_vexpand(state->chapters, TRUE); gtk_box_append(GTK_BOX(assemble), state->chapters);
  g_signal_connect(state->podcast_title, "changed", G_CALLBACK(edit_changed), state);
  g_signal_connect(state->episode_title, "changed", G_CALLBACK(edit_changed), state);
  g_signal_connect(gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->summary)), "changed", G_CALLBACK(edit_changed), state);
  g_signal_connect(gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->chapters)), "changed", G_CALLBACK(edit_changed), state);
  gtk_stack_add_titled(GTK_STACK(stack), assemble, "assemble", "Assemble & Encode");
  GtkWidget *transcribe = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  gtk_widget_set_margin_start(transcribe, 24); gtk_widget_set_margin_end(transcribe, 24); gtk_widget_set_margin_top(transcribe, 24); gtk_widget_set_margin_bottom(transcribe, 24);
  state->provider = gtk_drop_down_new(NULL, NULL); gtk_box_append(GTK_BOX(transcribe), state->provider);
  GtkWidget *transcription_actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
  GtkWidget *transcribe_button = gtk_button_new_with_label("Transcribe locally"); g_signal_connect(transcribe_button, "clicked", G_CALLBACK(transcribe_clicked), state); gtk_box_append(GTK_BOX(transcription_actions), transcribe_button);
  GtkWidget *models_button = gtk_button_new_with_label("Manage Models…"); g_signal_connect(models_button, "clicked", G_CALLBACK(models_clicked), state); gtk_box_append(GTK_BOX(transcription_actions), models_button);
  gtk_box_append(GTK_BOX(transcribe), transcription_actions);
  state->transcript = gtk_text_view_new(); gtk_widget_set_vexpand(state->transcript, TRUE); gtk_box_append(GTK_BOX(transcribe), state->transcript);
  g_signal_connect(gtk_text_view_get_buffer(GTK_TEXT_VIEW(state->transcript)), "changed", G_CALLBACK(edit_changed), state);
  gtk_stack_add_titled(GTK_STACK(stack), transcribe, "transcribe", "Transcribe");
  GtkWidget *footer = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8); gtk_widget_set_margin_start(footer, 12); gtk_widget_set_margin_end(footer, 12); gtk_widget_set_margin_top(footer, 8); gtk_widget_set_margin_bottom(footer, 8);
  state->status = gtk_label_new("Import an audio folder to begin."); gtk_widget_set_hexpand(state->status, TRUE); gtk_widget_set_halign(state->status, GTK_ALIGN_START); gtk_box_append(GTK_BOX(footer), state->status);
  state->cancel = gtk_button_new_with_label("Cancel"); gtk_widget_set_visible(state->cancel, FALSE); g_signal_connect(state->cancel, "clicked", G_CALLBACK(cancel_clicked), state); gtk_box_append(GTK_BOX(footer), state->cancel);
  gtk_box_append(GTK_BOX(root), header); gtk_box_append(GTK_BOX(root), stack); gtk_box_append(GTK_BOX(root), footer);
  gtk_widget_set_vexpand(stack, TRUE);
  adw_application_window_set_content(state->window, root);
  gtk_window_present(GTK_WINDOW(state->window));
  if (state->pending_open) {
    gchar *path = g_steal_pointer(&state->pending_open);
    run_engine(state, "open", path, NULL);
    g_free(path);
  } else {
    run_engine(state, "load-recovery", NULL, NULL);
  }
}

static void open_files(GApplication *application, GFile **files, gint file_count, const gchar *hint, gpointer user_data) {
  AppState *state = user_data;
  if (file_count < 1) return;
  g_free(state->pending_open);
  state->pending_open = g_file_get_path(files[0]);
  if (!state->window) {
    g_application_activate(application);
  } else if (!state->process) {
    gchar *path = g_steal_pointer(&state->pending_open);
    run_engine(state, "open", path, NULL);
    g_free(path);
  }
}

int main(int argc, char **argv) {
  AppState state = {0};
  state.provider_ids = g_ptr_array_new_with_free_func(g_free);
  state.application = adw_application_new("com.tlolabs.encap", G_APPLICATION_HANDLES_OPEN);
  g_signal_connect(state.application, "activate", G_CALLBACK(activate), &state);
  g_signal_connect(state.application, "open", G_CALLBACK(open_files), &state);
  int status = g_application_run(G_APPLICATION(state.application), argc, argv);
  if (state.recovery_source) g_source_remove(state.recovery_source);
  if (state.project) json_node_unref(state.project);
  g_ptr_array_unref(state.provider_ids);
  g_clear_object(&state.process);
  g_clear_object(&state.application);
  g_free(state.payload_path); g_free(state.operation); g_free(state.pending_open);
  return status;
}
