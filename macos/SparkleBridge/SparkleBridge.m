#import "SparkleBridge.h"

#import <Foundation/Foundation.h>
#import <objc/message.h>
#import <objc/runtime.h>

static id EnCapUpdaterController;

bool EnCapStartUpdater(void) {
    if (EnCapUpdaterController != nil) {
        return true;
    }

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

    id allocated = ((id (*)(id, SEL))objc_msgSend)(controllerClass, sel_registerName("alloc"));
    EnCapUpdaterController = ((id (*)(id, SEL, BOOL, id, id))objc_msgSend)(
        allocated,
        initializer,
        YES,
        nil,
        nil
    );
    return EnCapUpdaterController != nil;
}

bool EnCapCheckForUpdates(void) {
    if (!EnCapStartUpdater()) {
        return false;
    }

    SEL updaterSelector = NSSelectorFromString(@"updater");
    id updater = ((id (*)(id, SEL))objc_msgSend)(EnCapUpdaterController, updaterSelector);
    SEL checkSelector = NSSelectorFromString(@"checkForUpdates:");
    if (updater == nil || ![updater respondsToSelector:checkSelector]) {
        return false;
    }
    ((void (*)(id, SEL, id))objc_msgSend)(updater, checkSelector, nil);
    return true;
}
