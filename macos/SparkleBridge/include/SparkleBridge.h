#ifndef SparkleBridge_h
#define SparkleBridge_h

#include <stdbool.h>

void EnCapSetUpdateWorkInProgress(bool working);
void EnCapLinkedWorkStarted(void);
void EnCapLinkedWorkFinished(void);
bool EnCapStartUpdater(void);
bool EnCapCheckForUpdates(void);

#endif
