#import <Cocoa/Cocoa.h>
#import <Carbon/Carbon.h>

static NSString *const AppName = @"Claude 接续助手";
static NSString *const DialogPrefix = @"@@HANDOFF_DIALOG@@";

static NSString *RunDialog(NSString *source, NSArray<NSString *> *arguments, NSError **failure) {
    NSString *clean = [source stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *body = source;
    if ([clean hasPrefix:@"on run argv"] && [clean hasSuffix:@"end run"]) {
        NSUInteger start = @"on run argv".length;
        body = [clean substringWithRange:NSMakeRange(start, clean.length - start - @"end run".length)];
    }
    NSString *wrapped = [NSString stringWithFormat:@"on bridgeRun(argv)\n%@\nend bridgeRun", body];
    NSAppleScript *script = [[NSAppleScript alloc] initWithSource:wrapped];
    NSAppleEventDescriptor *event = [NSAppleEventDescriptor
        appleEventWithEventClass:kASAppleScriptSuite eventID:kASSubroutineEvent
        targetDescriptor:nil returnID:kAutoGenerateReturnID transactionID:kAnyTransactionID];
    [event setParamDescriptor:[NSAppleEventDescriptor descriptorWithString:@"bridgerun"] forKeyword:keyASSubroutineName];
    NSAppleEventDescriptor *argv = NSAppleEventDescriptor.listDescriptor;
    for (NSUInteger i = 0; i < arguments.count; i++) {
        [argv insertDescriptor:[NSAppleEventDescriptor descriptorWithString:arguments[i]] atIndex:i + 1];
    }
    NSAppleEventDescriptor *parameters = NSAppleEventDescriptor.listDescriptor;
    [parameters insertDescriptor:argv atIndex:1];
    [event setParamDescriptor:parameters forKeyword:keyDirectObject];
    NSDictionary *info = nil;
    NSAppleEventDescriptor *result = [script executeAppleEvent:event error:&info];
    if (info) {
        NSInteger code = [info[NSAppleScriptErrorNumber] integerValue];
        if (code == -128) return nil;
        if (failure) *failure = [NSError errorWithDomain:@"Handoff" code:code userInfo:@{
            NSLocalizedDescriptionKey: info[NSAppleScriptErrorMessage] ?: @"无法显示操作窗口。"}];
        return nil;
    }
    return result.stringValue;
}

@interface AppDelegate : NSObject <NSApplicationDelegate>
@property(strong) NSTask *worker;
@property(strong) NSPipe *input;
@property(strong) NSPipe *output;
@property(strong) NSPipe *errors;
@property(strong) NSMutableData *buffer;
@property(strong) NSMutableData *errorData;
@property(strong) NSMutableArray<NSString *> *messages;
@property BOOL stdoutEnded;
@property BOOL stderrEnded;
@property BOOL stopped;
@property BOOL completed;
@property int status;
@end

@implementation AppDelegate
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSMenu *menu = [[NSMenu alloc] init];
    NSMenuItem *item = [[NSMenuItem alloc] init];
    [menu addItem:item];
    NSMenu *applicationMenu = [[NSMenu alloc] init];
    NSMenuItem *about = [applicationMenu addItemWithTitle:[@"关于" stringByAppendingString:AppName]
        action:@selector(showAbout:) keyEquivalent:@""];
    about.target = self;
    [applicationMenu addItem:NSMenuItem.separatorItem];
    [applicationMenu addItemWithTitle:[@"退出" stringByAppendingString:AppName]
        action:@selector(terminate:) keyEquivalent:@"q"];
    item.submenu = applicationMenu;
    NSApp.mainMenu = menu;
    [self startWorker];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)visible {
    [NSApp activateIgnoringOtherApps:YES];
    if (!self.worker && !self.completed) [self startWorker];
    return YES;
}
- (void)applicationWillTerminate:(NSNotification *)notification {
    if (self.worker.running) [self.worker terminate];
}
- (void)showAbout:(id)sender {
    [NSApp orderFrontStandardAboutPanelWithOptions:@{
        NSAboutPanelOptionApplicationName: AppName,
        NSAboutPanelOptionApplicationVersion: @"1.2.0",
        NSAboutPanelOptionCredits: [[NSAttributedString alloc] initWithString:
            @"本机项目与会话接续工具\n账号在 Claude 官方客户端登录"]}];
}
- (void)showError:(NSString *)message {
    self.completed = YES;
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"未完成操作";
    alert.informativeText = message;
    alert.alertStyle = NSAlertStyleWarning;
    [alert addButtonWithTitle:@"关闭"];
    [NSApp activateIgnoringOtherApps:YES];
    [alert runModal];
    [NSApp terminate:nil];
}
- (void)startWorker {
    if (self.worker) return;
    NSURL *resources = NSBundle.mainBundle.resourceURL;
    NSData *data = [NSData dataWithContentsOfURL:[resources URLByAppendingPathComponent:@"runtime.json"]];
    NSDictionary *runtime = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    NSString *python = runtime[@"python"];
    if (![python isKindOfClass:NSString.class] || ![NSFileManager.defaultManager isExecutableFileAtPath:python]) {
        [self showError:@"本机 Python 运行环境不可用，请重新安装工具。"];
        return;
    }
    NSURL *tool = [resources URLByAppendingPathComponent:@"tool"];
    NSURL *script = [tool URLByAppendingPathComponent:@"handoff.py"];
    if (![NSFileManager.defaultManager fileExistsAtPath:script.path]) {
        [self showError:@"应用包中的程序文件缺失，请重新安装。"];
        return;
    }
    NSTask *process = [[NSTask alloc] init];
    process.executableURL = [NSURL fileURLWithPath:python];
    process.arguments = @[script.path, @"ui"];
    process.currentDirectoryURL = tool;
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    NSString *userDirectory = NSFileManager.defaultManager.homeDirectoryForCurrentUser.path;
    NSArray *paths = @[runtime[@"claude_bin"] ?: @"", @"/opt/homebrew/bin", @"/usr/local/bin",
        [userDirectory stringByAppendingPathComponent:@".local/bin"],
        [userDirectory stringByAppendingPathComponent:@".npm-global/bin"],
        environment[@"PATH"] ?: @"/usr/bin:/bin:/usr/sbin:/sbin"];
    environment[@"PATH"] = [paths componentsJoinedByString:@":"];
    environment[@"HANDOFF_APP_BRIDGE"] = @"1";
    environment[@"PYTHONDONTWRITEBYTECODE"] = @"1";
    environment[@"PYTHONUNBUFFERED"] = @"1";
    process.environment = environment;
    self.input = NSPipe.pipe;
    self.output = NSPipe.pipe;
    self.errors = NSPipe.pipe;
    process.standardInput = self.input;
    process.standardOutput = self.output;
    process.standardError = self.errors;
    self.worker = process;
    self.buffer = NSMutableData.data;
    self.errorData = NSMutableData.data;
    self.messages = NSMutableArray.array;
    self.stdoutEnded = self.stderrEnded = self.stopped = self.completed = NO;
    __weak AppDelegate *weakSelf = self;
    self.output.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *chunk = handle.availableData;
        if (!chunk.length) handle.readabilityHandler = nil;
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf receive:chunk isError:NO]; });
    };
    self.errors.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *chunk = handle.availableData;
        if (!chunk.length) handle.readabilityHandler = nil;
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf receive:chunk isError:YES]; });
    };
    process.terminationHandler = ^(NSTask *ended) {
        dispatch_async(dispatch_get_main_queue(), ^{
            weakSelf.stopped = YES;
            weakSelf.status = ended.terminationStatus;
            [weakSelf finishIfReady];
        });
    };
    NSError *error = nil;
    [NSApp activateIgnoringOtherApps:YES];
    if (![process launchAndReturnError:&error]) {
        self.output.fileHandleForReading.readabilityHandler = nil;
        self.errors.fileHandleForReading.readabilityHandler = nil;
        self.worker = nil;
        [self showError:error.localizedDescription];
    }
}
- (void)receive:(NSData *)chunk isError:(BOOL)isError {
    if (isError) {
        [self.errorData appendData:chunk];
        if (!chunk.length) self.stderrEnded = YES;
    } else {
        [self.buffer appendData:chunk];
        const unsigned char newline = '\n';
        NSData *separator = [NSData dataWithBytes:&newline length:1];
        while (YES) {
            NSRange end = [self.buffer rangeOfData:separator options:0 range:NSMakeRange(0, self.buffer.length)];
            if (end.location == NSNotFound) break;
            NSData *line = [self.buffer subdataWithRange:NSMakeRange(0, end.location)];
            [self.buffer replaceBytesInRange:NSMakeRange(0, end.location + 1) withBytes:NULL length:0];
            [self processLine:[[NSString alloc] initWithData:line encoding:NSUTF8StringEncoding] ?: @""];
        }
        if (!chunk.length) {
            self.stdoutEnded = YES;
            if (self.buffer.length) {
                [self processLine:[[NSString alloc] initWithData:self.buffer encoding:NSUTF8StringEncoding] ?: @""];
                [self.buffer setLength:0];
            }
        }
    }
    [self finishIfReady];
}
- (void)processLine:(NSString *)line {
    if (![line hasPrefix:DialogPrefix]) {
        if (line.length) [self.messages addObject:line];
        return;
    }
    NSData *payload = [[line substringFromIndex:DialogPrefix.length] dataUsingEncoding:NSUTF8StringEncoding];
    NSError *error = nil;
    id request = [NSJSONSerialization JSONObjectWithData:payload options:0 error:&error];
    NSString *value = nil;
    if ([request isKindOfClass:NSDictionary.class] && [request[@"script"] isKindOfClass:NSString.class]
        && [request[@"args"] isKindOfClass:NSArray.class]) {
        [NSApp activateIgnoringOtherApps:YES];
        value = RunDialog(request[@"script"], request[@"args"], &error);
    } else {
        error = [NSError errorWithDomain:@"Handoff" code:2 userInfo:@{NSLocalizedDescriptionKey:@"操作窗口数据无效。"}];
    }
    NSDictionary *response = error ? @{@"error":error.localizedDescription} : @{@"value":value ?: NSNull.null};
    NSMutableData *answer = [[NSJSONSerialization dataWithJSONObject:response options:0 error:nil] mutableCopy];
    [answer appendData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    @try { [self.input.fileHandleForWriting writeData:answer]; }
    @catch (NSException *exception) { [self.messages addObject:@"应用窗口已关闭。"]; }
}
- (void)finishIfReady {
    if (!(self.stopped && self.stdoutEnded && self.stderrEnded) || self.completed) return;
    self.completed = YES;
    self.worker = nil;
    self.input = self.output = self.errors = nil;
    NSString *errorText = [[[NSString alloc] initWithData:self.errorData encoding:NSUTF8StringEncoding]
        stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (errorText.length) [self.messages addObject:errorText];
    NSString *text = [self.messages componentsJoinedByString:@"\n"];
    if (!text.length) { [NSApp terminate:nil]; return; }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = self.status == 0 ? @"操作结果" : @"操作未完成";
    alert.informativeText = [text substringToIndex:MIN(text.length, 4000)];
    alert.alertStyle = self.status == 0 ? NSAlertStyleInformational : NSAlertStyleWarning;
    [alert addButtonWithTitle:@"返回菜单"];
    [alert addButtonWithTitle:@"关闭"];
    [NSApp activateIgnoringOtherApps:YES];
    if ([alert runModal] == NSAlertFirstButtonReturn) [self startWorker];
    else [NSApp terminate:nil];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if ([NSProcessInfo.processInfo.arguments containsObject:@"--self-test"]) {
            NSError *error = nil;
            NSString *test = @"中文 path $(literal) `unchanged`";
            NSString *value = RunDialog(@"on run argv\nreturn item 1 of argv\nend run", @[test], &error);
            if (error || ![value isEqualToString:test]) {
                fprintf(stderr, "Native argument bridge failed: %s\n", error.localizedDescription.UTF8String ?: "wrong result");
                return 1;
            }
            value = RunDialog(@"return \"ready\"", @[], &error);
            if (error || ![value isEqualToString:@"ready"]) return 1;
            puts("Native AppleScript argument bridge: OK");
            return 0;
        }
        NSApplication *application = NSApplication.sharedApplication;
        AppDelegate *delegate = [[AppDelegate alloc] init];
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
