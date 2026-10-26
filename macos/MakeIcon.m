#import <Cocoa/Cocoa.h>

static void Badge(NSString *letter, CGFloat x, CGFloat y, NSColor *color) {
    [color setFill];
    [[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(x-142, y-142, 284, 284)] fill];
    NSDictionary *attributes = @{NSFontAttributeName:[NSFont systemFontOfSize:158 weight:NSFontWeightSemibold],
                                NSForegroundColorAttributeName:NSColor.whiteColor};
    NSSize size = [letter sizeWithAttributes:attributes];
    [letter drawAtPoint:NSMakePoint(x-size.width/2, y-size.height/2) withAttributes:attributes];
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(1024,1024)];
        [image lockFocus];
        [[NSColor colorWithCalibratedRed:.12 green:.16 blue:.25 alpha:1] setFill];
        [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(48,48,928,928) xRadius:208 yRadius:208] fill];
        Badge(@"A",345,680,[NSColor colorWithCalibratedRed:.86 green:.45 blue:.29 alpha:1]);
        Badge(@"B",679,344,[NSColor colorWithCalibratedRed:.18 green:.63 blue:.63 alpha:1]);
        [NSColor.whiteColor setStroke];
        for (int flipped=0;flipped<2;flipped++) {
            NSAffineTransform *transform = NSAffineTransform.transform;
            [transform translateXBy:512 yBy:512];
            if (flipped) [transform rotateByDegrees:180];
            [transform translateXBy:-512 yBy:-512];
            NSBezierPath *curve = NSBezierPath.bezierPath;
            [curve moveToPoint:NSMakePoint(580,744)];
            [curve curveToPoint:NSMakePoint(812,543) controlPoint1:NSMakePoint(770,776) controlPoint2:NSMakePoint(826,691)];
            curve.lineWidth=36; curve.lineCapStyle=NSLineCapStyleRound;
            [curve transformUsingAffineTransform:transform]; [curve stroke];
            NSBezierPath *arrow=NSBezierPath.bezierPath;
            [arrow moveToPoint:NSMakePoint(760,590)]; [arrow lineToPoint:NSMakePoint(812,531)]; [arrow lineToPoint:NSMakePoint(862,593)];
            arrow.lineWidth=34; arrow.lineJoinStyle=NSLineJoinStyleRound; arrow.lineCapStyle=NSLineCapStyleRound;
            [arrow transformUsingAffineTransform:transform]; [arrow stroke];
        }
        [image unlockFocus];
        NSRect rect=NSMakeRect(0,0,1024,1024);
        CGImageRef cg=[image CGImageForProposedRect:&rect context:nil hints:nil];
        NSBitmapImageRep *bitmap=[[NSBitmapImageRep alloc] initWithCGImage:cg];
        NSData *png=[bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
        if (![png writeToFile:[NSString stringWithUTF8String:argv[1]] atomically:YES]) return 1;
    }
    return 0;
}
