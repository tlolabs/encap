#pragma once
#include <gtk/gtk.h>
#include <json-glib/json-glib.h>

typedef void (*EnCapChaptersChanged)(gpointer user_data);
GtkWidget *encap_chapter_editor_new(EnCapChaptersChanged changed, gpointer user_data);
void encap_chapter_editor_set_project(GtkWidget *editor, JsonObject *project, gboolean apply_preference, gboolean only_new);
