#pragma once
#include <stdbool.h>

/* MMddyyyyHHmmss in recorder wall-clock time; output is at most "12:59 PM". */
bool encap_rounded_recording_time(const char *filename, char output[9]);
