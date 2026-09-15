#include "chapter_editor.h"
#include "chapter_names.h"
#include <glib/gstdio.h>

enum { ORIGINAL, NUMBERED, TIME, CUSTOM };

typedef struct {
  GtkWidget *list;
  GtkWidget *style;
  GtkWidget *apply;
  JsonArray *chapters;
  JsonArray *sources;
  EnCapChaptersChanged changed;
  gpointer user_data;
} ChapterEditor;

static gchar *preference_path(void) {
  return g_build_filename(g_get_user_config_dir(), "encap", "chapter-naming.ini", NULL);
}

static guint load_style(void) {
  gchar *path = preference_path();
  GKeyFile *file = g_key_file_new();
  guint style = ORIGINAL;
  if (g_key_file_load_from_file(file, path, G_KEY_FILE_NONE, NULL)) {
    gint value = g_key_file_get_integer(file, "Chapters", "style", NULL);
    if (value >= ORIGINAL && value <= CUSTOM) style = (guint)value;
  }
  g_key_file_unref(file); g_free(path);
  return style;
}

static void update_apply(ChapterEditor *state) {
  gboolean custom = gtk_drop_down_get_selected(GTK_DROP_DOWN(state->style)) == CUSTOM;
  gtk_widget_set_sensitive(state->apply, state->chapters && json_array_get_length(state->chapters) > 0 && !custom);
  gtk_widget_set_tooltip_text(state->apply, custom
    ? "Custom names are edited directly in the chapter title fields below"
    : "Replace all chapter titles with the selected style. Time rounds filename timestamps to the nearest minute; other filenames keep their original names.");
}

static void style_changed(GObject *object, GParamSpec *property, gpointer data) {
  (void)object; (void)property;
  ChapterEditor *state = data;
  update_apply(state);
  gchar *path = preference_path(), *directory = g_path_get_dirname(path);
  GKeyFile *file = g_key_file_new();
  g_key_file_set_integer(file, "Chapters", "style", (gint)gtk_drop_down_get_selected(GTK_DROP_DOWN(state->style)));
  GError *error = NULL;
  if (g_mkdir_with_parents(directory, 0700) != 0 || !g_key_file_save_to_file(file, path, &error))
    g_warning("Could not save chapter naming preference: %s", error ? error->message : "cannot create config directory");
  g_clear_error(&error); g_key_file_unref(file); g_free(directory); g_free(path);
}

static void title_changed(GtkEditable *entry, gpointer data) {
  ChapterEditor *state = data;
  JsonObject *chapter = g_object_get_data(G_OBJECT(entry), "chapter");
  json_object_set_string_member(chapter, "title", gtk_editable_get_text(entry));
  gtk_drop_down_set_selected(GTK_DROP_DOWN(state->style), CUSTOM);
  state->changed(state->user_data);
}

static void present_rows(ChapterEditor *state) {
  GtkWidget *row;
  while ((row = gtk_widget_get_first_child(state->list))) gtk_list_box_remove(GTK_LIST_BOX(state->list), row);
  for (guint i = 0; state->chapters && i < json_array_get_length(state->chapters); i++) {
    JsonObject *chapter = json_array_get_object_element(state->chapters, i);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    gtk_widget_set_margin_top(box, 6); gtk_widget_set_margin_bottom(box, 6);
    gtk_widget_set_margin_start(box, 10); gtk_widget_set_margin_end(box, 10);
    gchar *number = g_strdup_printf("%u", i + 1);
    GtkWidget *label = gtk_label_new(number); g_free(number);
    gtk_widget_set_size_request(label, 28, -1);
    gtk_widget_add_css_class(label, "dim-label");
    GtkWidget *entry = gtk_entry_new();
    gtk_widget_set_hexpand(entry, TRUE);
    gtk_editable_set_text(GTK_EDITABLE(entry), json_object_get_string_member_with_default(chapter, "title", ""));
    gtk_accessible_update_property(GTK_ACCESSIBLE(entry), GTK_ACCESSIBLE_PROPERTY_LABEL, "Chapter title", -1);
    gtk_widget_set_tooltip_text(entry, "Type a custom name for this chapter");
    g_object_set_data_full(G_OBJECT(entry), "chapter", json_object_ref(chapter), (GDestroyNotify)json_object_unref);
    g_signal_connect(entry, "changed", G_CALLBACK(title_changed), state);
    gtk_box_append(GTK_BOX(box), label); gtk_box_append(GTK_BOX(box), entry);
    gtk_list_box_append(GTK_LIST_BOX(state->list), box);
  }
  update_apply(state);
}

static void apply_names(ChapterEditor *state, GHashTable *existing_ids) {
  guint style = gtk_drop_down_get_selected(GTK_DROP_DOWN(state->style));
  if (style == CUSTOM) return;
  for (guint i = 0; state->chapters && i < json_array_get_length(state->chapters); i++) {
    JsonObject *chapter = json_array_get_object_element(state->chapters, i);
    const gchar *id = json_object_get_string_member_with_default(chapter, "id", "");
    if (existing_ids && g_hash_table_contains(existing_ids, id)) continue;
    gint64 source_index = json_object_get_int_member_with_default(chapter, "chapter_number", 0) - 1;
    JsonObject *source = state->sources && source_index >= 0 && source_index < json_array_get_length(state->sources)
      ? json_array_get_object_element(state->sources, (guint)source_index) : NULL;
    if (style == NUMBERED) {
      gchar *title = g_strdup_printf("Chapter %u", i + 1);
      json_object_set_string_member(chapter, "title", title); g_free(title);
    } else if (source) {
      const gchar *name = json_object_get_string_member_with_default(source, "display_name", "");
      const gchar *path = json_object_get_string_member_with_default(source, "source_path", "");
      char rounded[9];
      const gchar *title = style == TIME && (encap_rounded_recording_time(name, rounded) || encap_rounded_recording_time(path, rounded)) ? rounded : name;
      json_object_set_string_member(chapter, "title", title);
    }
  }
}

static void apply_clicked(GtkButton *button, gpointer data) {
  (void)button;
  ChapterEditor *state = data;
  apply_names(state, NULL);
  present_rows(state);
  state->changed(state->user_data);
}

static void free_editor(gpointer data) {
  ChapterEditor *state = data;
  if (state->chapters) json_array_unref(state->chapters);
  if (state->sources) json_array_unref(state->sources);
  g_free(state);
}

GtkWidget *encap_chapter_editor_new(EnCapChaptersChanged changed, gpointer user_data) {
  ChapterEditor *state = g_new0(ChapterEditor, 1);
  state->changed = changed; state->user_data = user_data;
  GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
  GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
  GtkWidget *title = gtk_label_new("Chapters"); gtk_widget_add_css_class(title, "heading");
  gtk_box_append(GTK_BOX(header), title);
  gtk_box_append(GTK_BOX(header), gtk_label_new("Names"));
  const gchar *styles[] = {"Original", "Chapter #", "Time", "Custom", NULL};
  state->style = gtk_drop_down_new_from_strings(styles);
  gtk_drop_down_set_selected(GTK_DROP_DOWN(state->style), load_style());
  gtk_widget_set_tooltip_text(state->style, "Choose names for new imports, or apply them to current chapters. Custom lets you type your own titles.");
  gtk_accessible_update_property(GTK_ACCESSIBLE(state->style), GTK_ACCESSIBLE_PROPERTY_LABEL, "Chapter naming style", -1);
  state->apply = gtk_button_new_with_label("Apply");
  gtk_box_append(GTK_BOX(header), state->style); gtk_box_append(GTK_BOX(header), state->apply);
  gtk_box_append(GTK_BOX(root), header);
  state->list = gtk_list_box_new(); gtk_list_box_set_selection_mode(GTK_LIST_BOX(state->list), GTK_SELECTION_NONE);
  gtk_widget_add_css_class(state->list, "boxed-list");
  GtkWidget *scroll = gtk_scrolled_window_new();
  gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
  gtk_scrolled_window_set_min_content_height(GTK_SCROLLED_WINDOW(scroll), 150);
  gtk_widget_set_vexpand(scroll, TRUE); gtk_widget_set_vexpand(root, TRUE);
  gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll), state->list);
  gtk_box_append(GTK_BOX(root), scroll);
  g_signal_connect(state->style, "notify::selected", G_CALLBACK(style_changed), state);
  g_signal_connect(state->apply, "clicked", G_CALLBACK(apply_clicked), state);
  g_object_set_data_full(G_OBJECT(root), "chapter-editor", state, free_editor);
  update_apply(state);
  return root;
}

void encap_chapter_editor_set_project(GtkWidget *editor, JsonObject *project, gboolean apply_preference, gboolean only_new) {
  ChapterEditor *state = g_object_get_data(G_OBJECT(editor), "chapter-editor");
  GHashTable *existing = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
  if (only_new) {
    for (guint i = 0; state->chapters && i < json_array_get_length(state->chapters); i++) {
      JsonObject *chapter = json_array_get_object_element(state->chapters, i);
      g_hash_table_add(existing, g_strdup(json_object_get_string_member_with_default(chapter, "id", "")));
    }
  }
  if (state->chapters) json_array_unref(state->chapters);
  if (state->sources) json_array_unref(state->sources);
  state->chapters = json_array_ref(json_object_get_array_member(project, "chapters"));
  state->sources = json_array_ref(json_object_get_array_member(project, "audio_sources"));
  if (apply_preference) apply_names(state, only_new ? existing : NULL);
  present_rows(state);
  g_hash_table_unref(existing);
}
