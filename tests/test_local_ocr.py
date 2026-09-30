"""Native bridge contract and backend routing without contacting any service."""
import ast
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from local_ocr import apple_vision_text


def handler(backend='auto', platform='darwin'):
    # Load the actual class without initializing emulator/cache/scheduler globals.
    tree = ast.parse((ROOT / 'src/utils.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OCR_Handler')
    namespace = {'sys': SimpleNamespace(platform=platform), 'configs': SimpleNamespace(LOCAL_OCR_BACKEND=backend, GROQ_API_KEY=''), 'logger': Mock()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'utils.py', 'exec'), namespace)
    return namespace['OCR_Handler']


class RoutingTests(unittest.TestCase):
    def test_mac_prefers_vision_without_loading_easyocr(self):
        h = handler()
        with patch('local_ocr.apple_vision_text', return_value=['1 234']) as vision:
            self.assertEqual(h.get_text('frame'), ['1 234'])
            vision.assert_called_once_with('frame')
        self.assertFalse(hasattr(h, 'reader'))

    def test_empty_vision_result_remains_unknown(self):
        h = handler()
        with patch('local_ocr.apple_vision_text', return_value=[]):
            self.assertEqual(h.local_ocr('frame'), [])
        self.assertFalse(hasattr(h, 'reader'))

    def test_vision_failure_falls_back_and_cools_down_then_retries(self):
        h = handler()
        h.reader = Mock()
        h.reader.readtext.return_value = ['Army Camp', ' ']
        with patch('local_ocr.apple_vision_text', side_effect=RuntimeError('private failure')) as vision, patch('time.monotonic', return_value=100):
            self.assertEqual(h.local_ocr('frame'), ['Army Camp'])
            self.assertEqual(h.local_ocr('frame'), ['Army Camp'])
            self.assertEqual(vision.call_count, 1)
        with patch('time.monotonic', return_value=701), patch('local_ocr.apple_vision_text', return_value=['Wall']) as vision:
            self.assertEqual(h.local_ocr('frame'), ['Wall'])
            vision.assert_called_once()

    def test_other_platforms_and_explicit_easyocr_do_not_use_vision(self):
        for backend, platform in [('auto','win32'),('auto','linux'),('easyocr','darwin')]:
            with self.subTest(backend=backend, platform=platform):
                h = handler(backend, platform)
                reader = Mock()
                reader.readtext.return_value = ['Wall']
                module = SimpleNamespace(Reader=Mock(return_value=reader))
                with patch.dict(sys.modules, {'easyocr': module}), patch('local_ocr.apple_vision_text') as vision:
                    self.assertEqual(h.local_ocr('frame'), ['Wall'])
                    self.assertEqual(h.local_ocr('frame'), ['Wall'])
                vision.assert_not_called()
                module.Reader.assert_called_once_with(['en'], gpu=True)

    def test_interrupt_does_not_start_fallback(self):
        h = handler()
        with patch('local_ocr.apple_vision_text', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): h.local_ocr('frame')
        self.assertFalse(hasattr(h, 'reader'))

    def test_existing_optional_groq_behavior_is_preserved(self):
        h = handler()
        h.get_text.__func__.__globals__['configs'].GROQ_API_KEY = 'test-placeholder'
        with patch.object(h, 'external_ocr', return_value=['Cloud']), patch.object(h, 'local_ocr') as local:
            self.assertEqual(h.get_text('frame'), ['Cloud'])
            local.assert_not_called()


class BridgeTests(unittest.TestCase):
    def modules(self, success=True, error=None):
        request = Mock()
        request.results.return_value = [Mock(topCandidates_=Mock(return_value=[Mock(string=Mock(return_value='12 345'))])), Mock(topCandidates_=Mock(return_value=[])), Mock(topCandidates_=Mock(return_value=[Mock(string=Mock(return_value='  '))]))]
        vision = SimpleNamespace(VNRequestTextRecognitionLevelAccurate=1,
            VNRecognizeTextRequest=Mock(), VNImageRequestHandler=Mock())
        vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = request
        vision.VNImageRequestHandler.alloc.return_value.initWithData_options_.return_value.performRequests_error_.return_value = (success, error)
        foundation = SimpleNamespace(NSData=Mock(), NSDictionary=Mock())
        return {'Vision':vision,'Foundation':foundation,'objc':SimpleNamespace(autorelease_pool=nullcontext)}, request

    def test_lossless_png_bridge_and_literal_recognition(self):
        import cv2
        import numpy as np
        frame = np.zeros((12, 30, 3), dtype=np.uint8)
        frame[:,:,0] = 255
        modules, request = self.modules()
        with patch.dict(sys.modules, modules):
            self.assertEqual(apple_vision_text(frame), ['12 345'])
        data, size = modules['Foundation'].NSData.dataWithBytes_length_.call_args.args
        self.assertEqual(len(data), size)
        self.assertTrue(np.array_equal(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), frame))
        request.setRecognitionLanguages_.assert_called_once_with(['en-US'])
        request.setUsesLanguageCorrection_.assert_called_once_with(False)
        request.setRecognitionLevel_.assert_called_once_with(1)

    def test_native_failure_is_not_an_empty_success(self):
        import numpy as np
        for success, error in [(False,None),(True,object())]:
            modules, _ = self.modules(success, error)
            with patch.dict(sys.modules, modules), self.assertRaises(RuntimeError):
                apple_vision_text(np.zeros((10,10),dtype=np.uint8))

    def test_handler_options_are_a_native_dictionary(self):
        import numpy as np
        modules, _ = self.modules()
        native_options = object()
        modules['Foundation'].NSDictionary.dictionary.return_value = native_options
        initializer = modules['Vision'].VNImageRequestHandler.alloc.return_value.initWithData_options_
        original_handler = initializer.return_value

        def initialize(data, options):
            if options is not native_options:
                raise ValueError('NSInvalidArgumentException - key does not exist')
            return original_handler

        initializer.side_effect = initialize
        with patch.dict(sys.modules, modules):
            self.assertEqual(apple_vision_text(np.zeros((10,10),dtype=np.uint8)), ['12 345'])
        modules['Foundation'].NSDictionary.dictionary.assert_called_once_with()

    @unittest.skipUnless(sys.platform == 'darwin', 'Requires native Apple Vision on macOS')
    def test_native_mac_recognizes_rendered_number(self):
        import cv2
        import numpy as np
        frame = np.full((130, 600, 3), 255, dtype=np.uint8)
        cv2.putText(frame, '123456', (30,95), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0,0,0), 4)
        self.assertIn('123456', ''.join(apple_vision_text(frame)).replace(' ', ''))
