#include "source_waveform.h"
#include <json-glib/json-glib.h>
#include <unistd.h>

#define PEAK_COUNT 64

typedef struct { gboolean valid; double values[PEAK_COUNT]; } Peaks;
typedef struct { GWeakRef widget; gchar *path; } Job;
struct EnCapWaveforms {
  gint refs;
  gboolean disposed;
  GQueue pending;
  GHashTable *cache;
  GSubprocess *process;
  GCancellable *cancel;
  guint timer;
  Job *active;
  gchar *engine;
};
typedef struct { EnCapWaveforms *loader; gchar *path; gboolean queued, loaded; Peaks peaks; } Waveform;

static void pump(EnCapWaveforms *loader);
static void mapped(GtkWidget *widget, gpointer data);
static gboolean is_visible(GtkWidget *widget) {
  if (!gtk_widget_get_mapped(widget)) return FALSE;
  GtkWidget *scroll = gtk_widget_get_ancestor(widget, GTK_TYPE_SCROLLED_WINDOW);
  if (!scroll) return TRUE;
  graphene_rect_t bounds, viewport = GRAPHENE_RECT_INIT(0, 0, gtk_widget_get_width(scroll), gtk_widget_get_height(scroll));
  return gtk_widget_compute_bounds(widget, scroll, &bounds) && graphene_rect_intersection(&bounds, &viewport, NULL);
}
static void loader_unref(EnCapWaveforms *loader) {
  if (--loader->refs) return;
  g_hash_table_unref(loader->cache); g_clear_object(&loader->cancel); g_free(loader->engine); g_free(loader);
}
static void job_free(Job *job) { g_weak_ref_clear(&job->widget); g_free(job->path); g_free(job); }
static void waveform_free(gpointer data) {
  Waveform *waveform = data; loader_unref(waveform->loader); g_free(waveform->path); g_free(waveform);
}

static void draw(GtkDrawingArea *area, cairo_t *cr, gint width, gint height, gpointer data) {
  Waveform *waveform = data;
  if (width < 3 || height < 1) return;
  mapped(GTK_WIDGET(area), data);
  if (!waveform->peaks.valid) return;
  GdkRGBA color; gtk_style_context_get_color(gtk_widget_get_style_context(GTK_WIDGET(area)), &color);
  gdk_cairo_set_source_rgba(cr, &color);
  gint count = MIN(PEAK_COUNT, MAX(1, width / 3));
  double step = (double)width / count;
  for (gint bar = 0; bar < count; bar++) {
    double peak = 0;
    for (gint sample = PEAK_COUNT * bar / count; sample < PEAK_COUNT * (bar + 1) / count; sample++) peak = MAX(peak, waveform->peaks.values[sample]);
    double bar_height = MAX(1, height * CLAMP(peak, 0, 1));
    cairo_rectangle(cr, bar * step, height - bar_height, MAX(1, step - 1), bar_height);
  }
  cairo_fill(cr);
}

static void apply(Job *job, const Peaks *peaks) {
  GtkWidget *widget = g_weak_ref_get(&job->widget);
  if (!widget) return;
  Waveform *waveform = g_object_get_data(G_OBJECT(widget), "waveform");
  waveform->peaks = *peaks; waveform->loaded = TRUE; waveform->queued = FALSE;
  gtk_widget_queue_draw(widget); g_object_unref(widget);
}

static void loaded(GObject *process, GAsyncResult *result, gpointer data) {
  EnCapWaveforms *loader = data;
  gchar *output = NULL, *diagnostics = NULL;
  gboolean success = g_subprocess_communicate_utf8_finish(G_SUBPROCESS(process), result, &output, &diagnostics, NULL);
  Peaks peaks = {0};
  if (!loader->disposed && success && g_subprocess_get_successful(G_SUBPROCESS(process)) && output) {
    JsonParser *parser = json_parser_new();
    if (json_parser_load_from_data(parser, output, -1, NULL)) {
      JsonNode *root = json_parser_get_root(parser);
      if (JSON_NODE_HOLDS_OBJECT(root)) {
        JsonObject *object = json_node_get_object(root);
        JsonNode *node = json_object_get_member(object, "peaks");
        if (node && JSON_NODE_HOLDS_ARRAY(node)) {
          JsonArray *array = json_node_get_array(node);
          if (json_array_get_length(array) == PEAK_COUNT) {
            peaks.valid = TRUE;
            for (guint i = 0; i < PEAK_COUNT; i++) peaks.values[i] = CLAMP(json_array_get_double_element(array, i), 0, 1);
          }
        }
      }
    }
    g_object_unref(parser);
  }
  if (!loader->disposed) {
    if (g_hash_table_size(loader->cache) >= 512) {
      GHashTableIter iter; g_hash_table_iter_init(&iter, loader->cache);
      if (g_hash_table_iter_next(&iter, NULL, NULL)) g_hash_table_iter_remove(&iter);
    }
    g_hash_table_replace(loader->cache, g_strdup(loader->active->path), g_memdup2(&peaks, sizeof peaks));
    apply(loader->active, &peaks);
  }
  g_free(output); g_free(diagnostics);
  job_free(loader->active); loader->active = NULL;
  g_clear_object(&loader->process);
  if (!loader->disposed) pump(loader);
  loader_unref(loader);
}

static void lower_priority(gpointer data) { (void)data; (void)nice(10); }

static void pump(EnCapWaveforms *loader) {
  if (loader->disposed || loader->process) return;
  while (!g_queue_is_empty(&loader->pending)) {
    Job *job = g_queue_pop_head(&loader->pending);
    GtkWidget *widget = g_weak_ref_get(&job->widget);
    gboolean visible = widget && is_visible(widget);
    if (widget && !visible) {
      Waveform *waveform = g_object_get_data(G_OBJECT(widget), "waveform"); waveform->queued = FALSE;
    }
    g_clear_object(&widget);
    if (!visible) { job_free(job); continue; }
    GSubprocessLauncher *launcher = g_subprocess_launcher_new(G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_PIPE);
    g_subprocess_launcher_set_child_setup(launcher, lower_priority, NULL, NULL);
    loader->process = g_subprocess_launcher_spawn(launcher, NULL, loader->engine, "waveform", "--", job->path, NULL);
    g_object_unref(launcher);
    if (!loader->process) { Peaks empty = {0}; apply(job, &empty); job_free(job); continue; }
    loader->active = job; loader->refs++;
    g_subprocess_communicate_utf8_async(loader->process, NULL, loader->cancel, loaded, loader);
    return;
  }
}

static gboolean deferred_pump(gpointer data) {
  EnCapWaveforms *loader = data; loader->timer = 0; pump(loader); return G_SOURCE_REMOVE;
}

static void mapped(GtkWidget *widget, gpointer data) {
  Waveform *waveform = data; EnCapWaveforms *loader = waveform->loader;
  if (loader->disposed || waveform->loaded || waveform->queued || !is_visible(widget)) return;
  const Peaks *cached = g_hash_table_lookup(loader->cache, waveform->path);
  if (cached) { waveform->peaks = *cached; waveform->loaded = TRUE; gtk_widget_queue_draw(widget); return; }
  Job *job = g_new0(Job, 1); g_weak_ref_init(&job->widget, widget); job->path = g_strdup(waveform->path);
  waveform->queued = TRUE; g_queue_push_tail(&loader->pending, job);
  if (!loader->process && !loader->timer) loader->timer = g_timeout_add_full(G_PRIORITY_LOW, 150, deferred_pump, loader, NULL);
}

EnCapWaveforms *encap_waveforms_new(void) {
  EnCapWaveforms *loader = g_new0(EnCapWaveforms, 1); loader->refs = 1;
  loader->cache = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);
  loader->cancel = g_cancellable_new();
  gchar *binary = g_file_read_link("/proc/self/exe", NULL);
  gchar *directory = binary ? g_path_get_dirname(binary) : NULL;
  loader->engine = directory ? g_build_filename(directory, "encap-engine", NULL) : g_strdup("encap-engine");
  g_free(binary); g_free(directory); return loader;
}

void encap_waveforms_free(EnCapWaveforms *loader) {
  loader->disposed = TRUE;
  if (loader->timer) g_source_remove(loader->timer);
  g_cancellable_cancel(loader->cancel);
  if (loader->process) g_subprocess_force_exit(loader->process);
  while (!g_queue_is_empty(&loader->pending)) job_free(g_queue_pop_head(&loader->pending));
  loader_unref(loader);
}

GtkWidget *encap_waveform_new(EnCapWaveforms *loader, const gchar *path) {
  GtkWidget *area = gtk_drawing_area_new();
  Waveform *waveform = g_new0(Waveform, 1); waveform->loader = loader; loader->refs++; waveform->path = g_strdup(path);
  gtk_widget_set_hexpand(area, TRUE); gtk_widget_set_size_request(area, 0, 12);
  gtk_widget_set_can_target(area, FALSE); gtk_widget_add_css_class(area, "source-waveform");
  gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(area), draw, waveform, NULL);
  g_object_set_data_full(G_OBJECT(area), "waveform", waveform, waveform_free);
  g_signal_connect(area, "map", G_CALLBACK(mapped), waveform);
  return area;
}
