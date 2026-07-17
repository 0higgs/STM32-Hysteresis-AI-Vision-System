import argparse
import os
import cv2
import numpy as np
import matplotlib.pyplot as plt

try:
    from skimage.morphology import skeletonize
    HAS_SKIMAGE = True
except Exception:
    HAS_SKIMAGE = False


def imread_any(path):
    """兼容一些扩展名是 jpg 但本质是 BMP 的示波器截图。"""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {path}")
    return img


def resize_keep_ratio(img, max_width=1400):
    h, w = img.shape[:2]
    if w <= max_width:
        return img
    s = max_width / w
    return cv2.resize(img, (int(w*s), int(h*s)))


def parse_roi(roi_str, img):
    h, w = img.shape[:2]
    if roi_str:
        x1, y1, x2, y2 = map(int, roi_str.split(','))
        x1, x2 = sorted([max(0, x1), min(w, x2)])
        y1, y2 = sorted([max(0, y1), min(h, y2)])
        return x1, y1, x2, y2
    return auto_roi(img)


def auto_roi(img):
    """
    自动找示波器绘图区：寻找大面积深色矩形区域。
    对手机实拍不一定完美；如果不准，用 --roi 手动给。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 深色区域：示波器绘图背景通常接近黑色
    dark = cv2.inRange(gray, 0, 55)
    kernel = np.ones((5, 5), np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = img.shape[:2]
    best = None
    best_score = -1
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        if bw < 0.25*w or bh < 0.25*h:
            continue
        # 避免把整张黑边当成绘图区；倾向接近方形/矩形的中央区域
        cx, cy = x + bw/2, y + bh/2
        center_penalty = abs(cx - w/2)/w + abs(cy - h/2)/h
        score = area * (1 - center_penalty)
        if score > best_score:
            best_score = score
            best = (x, y, x+bw, y+bh)

    if best is None:
        # 保守裁掉标题栏和底部文字：适合数字截图/手机正拍
        return int(0.15*w), int(0.10*h), int(0.85*w), int(0.88*h)

    x1, y1, x2, y2 = best
    # 收缩一点，尽量排除外框、文字和箭头
    padx = int(0.02 * (x2-x1))
    pady = int(0.02 * (y2-y1))
    return x1+padx, y1+pady, x2-padx, y2-pady


def trace_mask(roi_bgr, color='magenta'):
    """专门提取示波器亮色轨迹，不再把绿色文字/网格一起提出来。"""
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)

    if color == 'magenta':
        # OpenCV H: 0~179。你们这张图的紫色轨迹 H≈150。
        lower = np.array([135, 80, 80])
        upper = np.array([170, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    elif color == 'green':
        lower = np.array([35, 70, 70])
        upper = np.array([95, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    elif color == 'cyan':
        lower = np.array([80, 60, 60])
        upper = np.array([105, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    else:
        # 兜底：只取高亮高饱和区域
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]
        mask = ((s > 80) & (v > 120)).astype(np.uint8) * 255

    kernel = np.ones((2, 2), np.uint8)
    # 不做开运算，否则 1 像素粗的示波器轨迹会被直接抹掉
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    return mask


def keep_biggest(mask):
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if num <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    # 只保留最大几个连通域，防止轨迹断裂时被删光
    ids = np.argsort(areas)[-4:] + 1
    out = np.zeros_like(mask)
    for i in ids:
        if stats[i, cv2.CC_STAT_AREA] > 20:
            out[labels == i] = 255
    return out


def skeleton(mask):
    if not HAS_SKIMAGE:
        return mask
    sk = skeletonize(mask > 0).astype(np.uint8) * 255
    return sk


def points_from_mask(mask):
    ys, xs = np.where(mask > 0)
    return xs.astype(float), ys.astype(float)


def normalize_by_roi(xs, ys, roi_shape):
    """使用绘图区中心作为坐标原点，而不是使用曲线自身包围盒。"""
    h, w = roi_shape[:2]
    x0, y0 = (w - 1) / 2, (h - 1) / 2
    H = (xs - x0) / (w / 2)
    B = -(ys - y0) / (h / 2)
    return H, B


def band_intercepts(H, B, eps=0.035):
    """
    Br: H≈0 处 B 的正负交点；Hc: B≈0 处 H 的正负交点。
    用带状区域取中位数，适合从图像轨迹提取出的散点。
    """
    br_vals = B[np.abs(H) < eps]
    hc_vals = H[np.abs(B) < eps]

    def split_pm(vals):
        vals = np.asarray(vals)
        pos = vals[vals > 0]
        neg = vals[vals < 0]
        pos_m = float(np.median(pos)) if len(pos) else None
        neg_m = float(np.median(neg)) if len(neg) else None
        abs_m = None
        if pos_m is not None and neg_m is not None:
            abs_m = (abs(pos_m) + abs(neg_m)) / 2
        elif pos_m is not None:
            abs_m = abs(pos_m)
        elif neg_m is not None:
            abs_m = abs(neg_m)
        return pos_m, neg_m, abs_m

    Br_pos, Br_neg, Br_abs = split_pm(br_vals)
    Hc_pos, Hc_neg, Hc_abs = split_pm(hc_vals)
    return Br_pos, Br_neg, Br_abs, Hc_pos, Hc_neg, Hc_abs


def contour_area_norm(mask, roi_shape):
    """用闭合轨迹的外轮廓估计回线面积，返回归一化面积。"""
    h, w = roi_shape[:2]
    m = cv2.dilate(mask, np.ones((3,3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area_px = cv2.contourArea(c)
    # H,B 坐标归一化，x比例 2/w，y比例 2/h
    return float(area_px * (2/w) * (2/h))


def diagnose(H, B, params):
    msgs = []
    n = len(H)
    if n < 120:
        msgs.append('有效轨迹点偏少：图像可能过暗、模糊，或颜色阈值未对准。')
    if params['area*'] is not None and params['area*'] < 0.15:
        msgs.append('回线面积偏小：可能未充分磁化，或提取到的不是完整回线。')
    if params['Br_abs*'] is None:
        msgs.append('未稳定获得 Br：回线没有明显穿过 H=0 附近，或坐标原点需重新标定。')
    if params['Hc_abs*'] is None:
        msgs.append('未稳定获得 Hc：回线没有明显穿过 B=0 附近，或坐标原点需重新标定。')
    if not msgs:
        msgs.append('回线提取基本正常，可进入参数分析。')
    return msgs


def process(image_path, roi_str=None, color='magenta', outdir='output_v2'):
    img = resize_keep_ratio(imread_any(image_path))
    x1, y1, x2, y2 = parse_roi(roi_str, img)
    roi = img[y1:y2, x1:x2].copy()

    mask = trace_mask(roi, color=color)
    mask = keep_biggest(mask)
    sk = skeleton(mask)
    xs, ys = points_from_mask(sk)
    if len(xs) == 0:
        raise RuntimeError('没有提取到轨迹。请尝试 --color magenta/green/cyan，或用 --roi 手动裁剪绘图区。')

    H, B = normalize_by_roi(xs, ys, roi.shape)
    Br_pos, Br_neg, Br_abs, Hc_pos, Hc_neg, Hc_abs = band_intercepts(H, B)
    area = contour_area_norm(mask, roi.shape)
    params = {
        'points': int(len(xs)),
        'Hm*': float(np.max(np.abs(H))),
        'Bm*': float(np.max(np.abs(B))),
        'Br_pos*': Br_pos,
        'Br_neg*': Br_neg,
        'Br_abs*': Br_abs,
        'Hc_pos*': Hc_pos,
        'Hc_neg*': Hc_neg,
        'Hc_abs*': Hc_abs,
        'area*': area,
    }
    msgs = diagnose(H, B, params)

    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(image_path))[0]

    # 保存ROI、mask、overlay
    cv2.imwrite(os.path.join(outdir, base + '_roi.png'), roi)
    cv2.imwrite(os.path.join(outdir, base + '_mask.png'), mask)
    cv2.imwrite(os.path.join(outdir, base + '_skeleton.png'), sk)
    overlay = roi.copy()
    overlay[mask > 0] = (0, 255, 255)
    cv2.imwrite(os.path.join(outdir, base + '_overlay.png'), overlay)

    # 画回线散点
    plt.figure(figsize=(6,6))
    plt.scatter(H, B, s=2)
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.grid(True, alpha=0.5)
    plt.axis('equal')
    plt.xlabel('H*')
    plt.ylabel('B*')
    plt.title('Extracted hysteresis loop (v2)')
    lines = []
    for k in ['Hm*','Bm*','Br_abs*','Hc_abs*','area*']:
        v = params[k]
        lines.append(f'{k}: {v:.3f}' if v is not None else f'{k}: None')
    plt.text(0.02, 0.98, '\n'.join(lines), transform=plt.gca().transAxes,
             va='top', bbox=dict(boxstyle='round', alpha=0.15))
    plt.savefig(os.path.join(outdir, base + '_loop.png'), dpi=220, bbox_inches='tight')
    plt.close()

    # 标记ROI到原图
    boxed = img.copy()
    cv2.rectangle(boxed, (x1,y1), (x2,y2), (0,255,255), 2)
    cv2.imwrite(os.path.join(outdir, base + '_boxed_roi.png'), boxed)

    return params, msgs, (x1,y1,x2,y2)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--roi', default=None, help='手动ROI: x1,y1,x2,y2，例如 58,20,260,220')
    ap.add_argument('--color', default='magenta', choices=['magenta','green','cyan','auto'])
    ap.add_argument('--outdir', default='output_v2')
    args = ap.parse_args()

    params, msgs, roi = process(args.image, args.roi, args.color, args.outdir)
    print('ROI:', roi)
    print('==== 参数 ====')
    for k,v in params.items():
        if isinstance(v, float):
            print(f'{k}: {v:.4f}')
        else:
            print(f'{k}: {v}')
    print('==== 诊断 ====')
    for m in msgs:
        print('-', m)