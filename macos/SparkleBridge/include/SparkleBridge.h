#ifndef SparkleBridge_h
#define SparkleBridge_h

#include <stdbool.h>

void EnCapSetUpdateWorkInProgress(bool working);
bool EnCapStartUpdater(void);
bool EnCapCheckForUpdates(void);

#endif
