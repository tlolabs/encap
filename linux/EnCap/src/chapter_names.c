#include "chapter_names.h"
#include <stdio.h>
#include <string.h>

static int number(const char *text, unsigned start, unsigned length) {
  int value = 0;
  for (unsigned i = start; i < start + length; i++) value = value * 10 + text[i] - '0';
  return value;
}

bool encap_rounded_recording_time(const char *filename, char output[9]) {
  if (!filename) return false;
  for (const char *cursor = filename; *cursor; cursor++)
    if (*cursor == '/' || *cursor == '\\') filename = cursor + 1;
  if (strlen(filename) < 14) return false;
  for (unsigned i = 0; i < 14; i++) if (filename[i] < '0' || filename[i] > '9') return false;
  int month = number(filename, 0, 2), day = number(filename, 2, 2), year = number(filename, 4, 4);
  int hour = number(filename, 8, 2), minute = number(filename, 10, 2), second = number(filename, 12, 2);
  if (year < 1 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return false;
  const int days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
  bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
  int maximum = days[month - 1] + (month == 2 && leap ? 1 : 0);
  if (day < 1 || day > maximum) return false;
  int rounded = (hour * 60 + minute + (second >= 30 ? 1 : 0)) % 1440;
  hour = rounded / 60;
  snprintf(output, 9, "%d:%02d %s", hour % 12 == 0 ? 12 : hour % 12, rounded % 60, hour < 12 ? "AM" : "PM");
  return true;
}
