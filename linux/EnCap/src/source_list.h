#pragma once
#include <adwaita.h>
#include <json-glib/json-glib.h>

typedef void (*EnCapAddSources)(gpointer user_data);
typedef void (*EnCapRemoveSources)(GPtrArray *paths, gpointer user_data);
GtkWidget *encap_source_list_new(EnCapAddSources add, EnCapRemoveSources remove, gpointer user_data);
gint encap_source_list_set_sources(GtkWidget *widget, JsonArray *sources);
void encap_source_list_stop(GtkWidget *widget);
