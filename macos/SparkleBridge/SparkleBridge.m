#import "SparkleBridge.h"

#import <Foundation/Foundation.h>
#import <objc/message.h>
#import <objc/runtime.h>

static id EnCapUpdaterController;
static BOOL EnCapWorkInProgress;

// Sparkle is loaded dynamically; these selectors follow SPUUpdaterDelegate.
@interface EnCapUpdateDelegate : NSObject
@end
@implementation EnCapUpdateDelegate
- (BOOL)updater:(id)updater mayPerformUpdateCheck:(NSInteger)check error:(NSError **)error {
    if (EnCapWorkInProgress && error) *error = [NSError errorWithDomain:@"com.tlolabs.encap.updates" code:1 userInfo:@{NSLocalizedDescriptionKey:@"Finish the current operation before updating."}];
    return !EnCapWorkInProgress;
}
- (BOOL)updater:(id)updater shouldProceedWithUpdate:(id)item updateCheck:(NSInteger)check error:(NSError **)error {
    return [self updater:updater mayPerformUpdateCheck:check error:error];
}
- (NSArray *)allowedSystemProfileKeysForUpdater:(id)updater { return @[]; }
- (BOOL)updater:(id)updater shouldPostponeRelaunchForUpdate:(id)item untilInvokingBlock:(void (^)(void))installHandler {
    if (!EnCapWorkInProgress) return NO;
    [NSTimer scheduledTimerWithTimeInterval:1.0 repeats:YES block:^(NSTimer *timer) {
        if (!EnCapWorkInProgress) { [timer invalidate]; installHandler(); }
    }];
    return YES;
}
@end
static EnCapUpdateDelegate *EnCapUpdaterDelegate;
void EnCapSetUpdateWorkInProgress(bool working) { EnCapWorkInProgress = working; }


bool EnCapStartUpdater(void) {
    if (EnCapUpdaterController != nil) {
        return true;
    }

    NSString *key = [NSBundle.mainBundle objectForInfoDictionaryKey:@"SUPublicEDKey"];
    if (key == nil || [[NSData alloc] initWithBase64EncodedString:key options:0].length != 32) return false;
    NSString *frameworkPath = [NSBundle.mainBundle.privateFrameworksPath
        stringByAppendingPathComponent:@"Sparkle.framework"];
    NSBundle *framework = [NSBundle bundleWithPath:frameworkPath];
    if (framework == nil || ![framework load]) {
        return false;
    }

    Class controllerClass = NSClassFromString(@"SPUStandardUpdaterController");
    SEL initializer = NSSelectorFromString(
        @"initWithStartingUpdater:updaterDelegate:userDriverDelegate:"
    );
    if (controllerClass == Nil || ![controllerClass instancesRespondToSelector:initializer]) {
        return false;
    }

    EnCapUpdaterDelegate = [EnCapUpdateDelegate new];
    id allocated = ((id (*)(id, SEL))objc_msgSend)(controllerClass, sel_registerName("alloc"));
    EnCapUpdaterController = ((id (*)(id, SEL, BOOL, id, id))objc_msgSend)(
        allocated,
        initializer,
        YES,
        EnCapUpdaterDelegate,
        nil
    );
    return EnCapUpdaterController != nil;
}

bool EnCapCheckForUpdates(void) {
    if (!EnCapStartUpdater()) {
        return false;
    }

    id updater = EnCapUpdaterController;
    SEL checkSelector = NSSelectorFromString(@"checkForUpdates:");
    if (updater == nil || ![updater respondsToSelector:checkSelector]) {
        return false;
    }
    ((void (*)(id, SEL, id))objc_msgSend)(updater, checkSelector, nil);
    return true;
}
