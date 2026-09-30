"""Read-only local UI inventory. Never taps, navigates or rewrites templates."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from android_startup import PACKAGE, ensure_android
from purchase_safety import purchase_reason


def scan(device, output, ocr, count=1, interval=2):
    import cv2
    import numpy as np
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    package_info = device.shell(['dumpsys','package',PACKAGE])
    versions = {key: re.search(r'\b'+key+r'=([^\s]+)',package_info).group(1)
                for key in ('versionName','versionCode') if re.search(r'\b'+key+r'=([^\s]+)',package_info)}
    observations = []
    assets = [ROOT/'assets/upgrader/confirm.png', ROOT/'assets/upgrader/upgrade.png',
              ROOT/'assets/attacker/return_home.png', ROOT/'assets/attacker/end_battle.png',
              ROOT/'assets/misc/slash.png']
    for index in range(count):
        image = device.screenshot(error_ok=False)
        frame = np.array(image.convert('RGB'))
        texts = ocr(frame)
        scores = {}
        gray = cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)
        for asset in assets:
            template = cv2.imread(str(asset),cv2.IMREAD_GRAYSCALE)
            if template is None or template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
                continue
            score = float(cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))[1])
            scores[str(asset.relative_to(ROOT))] = {'score':score,'sha256':hashlib.sha256(asset.read_bytes()).hexdigest()}
        name = f'screen-{index:03d}.png'
        image.save(output/name)
        (output/name).chmod(0o600)
        observations.append({'timestamp':time.time(),'foreground_package':device.app_current().package,
                             'size':list(image.size),'screenshot':name,'ocr':texts,
                             'purchase_block_reason':purchase_reason(texts),'template_scores':scores})
        if index+1<count: time.sleep(interval)
    report = {'app_version':versions,'observations':observations,'review_required':True,
              'templates_updated':False,'inputs_sent':0,'model_requests':0}
    path = output/'report.json'
    path.write_text(json.dumps(report,indent=2))
    path.chmod(0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=1)
    parser.add_argument('--interval',type=float,default=2)
    parser.add_argument('--output',default=None)
    args = parser.parse_args()
    if not 1<=args.samples<=60 or not .5<=args.interval<=10:
        parser.error('samples must be 1..60; interval must be .5..10 seconds')
    import adbutils
    from utils import OCR_Handler
    address = ensure_android(adbutils.adb,start=False)
    output = args.output or f'debug/ui-scan/{time.time_ns()}'
    scan(adbutils.device(address),output,OCR_Handler.local_ocr,args.samples,args.interval)
    print(f'Local UI inventory saved to {output}. No inputs or model requests sent. Review private text before sharing.')


if __name__=='__main__': main()
