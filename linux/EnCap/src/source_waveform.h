#pragma once
#include <gtk/gtk.h>

typedef struct EnCapWaveforms EnCapWaveforms;
EnCapWaveforms *encap_waveforms_new(void);
void encap_waveforms_free(EnCapWaveforms *loader);
GtkWidget *encap_waveform_new(EnCapWaveforms *loader, const gchar *path);
