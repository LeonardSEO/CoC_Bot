"""Local text recognition. Apple frameworks are imported only when requested."""


def apple_vision_text(frame):
    """Recognize an OpenCV BGR/grayscale image entirely on the Mac.

    PNG encoding preserves channel order and avoids temporary screenshot files.
    Empty recognition is a valid result; framework failures raise for fallback.
    """
    import cv2
    import objc
    import Foundation
    import Vision

    encoded, image = cv2.imencode('.png', frame)
    if not encoded:
        raise ValueError('Could not encode OCR image')
    data = image.tobytes()
    with objc.autorelease_pool():
        image_data = Foundation.NSData.dataWithBytes_length_(data, len(data))
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(['en-US'])
        # Resource amounts and game names must not be autocorrected into words.
        request.setUsesLanguageCorrection_(False)
        # A Python dict is bridged as a proxy. Native option-key lookups can
        # raise "key does not exist" on newer macOS; use a real NSDictionary.
        options = Foundation.NSDictionary.dictionary()
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(image_data, options)
        success, error = handler.performRequests_error_([request], None)
        if not success or error is not None:
            raise RuntimeError('Apple Vision recognition failed')
        texts = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                text = str(candidates[0].string())
                if text.strip():
                    texts.append(text)
        return texts
