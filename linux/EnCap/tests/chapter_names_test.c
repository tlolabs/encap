#include "chapter_names.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  FILE *file = fopen(argv[1], "r");
  if (!file) return 2;
  char line[512]; unsigned checked = 0;
  while (fgets(line, sizeof line, file)) {
    if (line[0] == '#' || line[0] == '\n') continue;
    char *expected = strchr(line, '\t');
    if (!expected) return 2;
    *expected++ = '\0'; expected[strcspn(expected, "\r\n")] = '\0';
    char output[9] = {0};
    bool valid = encap_rounded_recording_time(line, output);
    if (valid != (strcmp(expected, "-") != 0) || (valid && strcmp(output, expected) != 0)) {
      fprintf(stderr, "%s: expected %s, got %s\n", line, expected, valid ? output : "invalid");
      return 1;
    }
    checked++;
  }
  fclose(file);
  if (checked == 0) return 2;
  printf("Passed %u shared chapter timestamp cases.\n", checked);
  return 0;
}
