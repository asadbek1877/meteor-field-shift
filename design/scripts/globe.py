import sys
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter

D = '/home/claude/tex/x/package/example/'
LON0 = float(sys.argv[1]) if len(sys.argv) > 1 else 28.0
LAT0 = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
N, R = 1400, 500
W, H = 4096, 2048

bm = np.asarray(Image.open(D + 'img/earth-blue-marble.jpg').convert('RGB'), dtype=np.float32) / 255.0
topo = Image.open(D + 'img/earth-topology.png').convert('L').resize((W, H), Image.BICUBIC)
water = Image.open(D + 'img/earth-water.png').convert('L').resize((W, H), Image.BILINEAR)
cloud = np.asarray(Image.open(D + 'clouds/clouds.png').convert('RGBA'), dtype=np.float32)[..., 3] / 255.0
topo = gaussian_filter(np.asarray(topo, dtype=np.float32), 1.2)
water = np.asarray(water, dtype=np.float32) / 255.0

# hillshade in map space, light from the upper left
hy, hx = np.gradient(topo * 0.5)
ratio = (0.55 * hx + 0.55 * hy + 0.62) / np.sqrt(hx * hx + hy * hy + 1.0) / 0.62
shade = np.clip(1.0 + (ratio - 1.0) * 2.2, 0.55, 1.6)

# pixel grid
yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
x = (xx - (N - 1) / 2) / R
y = -(yy - (N - 1) / 2) / R
r2 = x * x + y * y
r = np.sqrt(r2)
inside = r2 < 1.0
z = np.sqrt(np.clip(1.0 - r2, 0, 1))

lat0, lon0 = np.radians(LAT0), np.radians(LON0)
sinphi = np.clip(z * np.sin(lat0) + y * np.cos(lat0), -1, 1)
phi = np.arcsin(sinphi)
lam = lon0 + np.arctan2(x, z * np.cos(lat0) - y * np.sin(lat0))
u = ((np.degrees(lam) + 180.0) % 360.0) / 360.0 * W
v = (90.0 - np.degrees(phi)) / 180.0 * H
iu, iv = u[inside], v[inside]
co = [iv, iu]


def samp(a):
    return map_coordinates(a, co, order=1, mode='grid-wrap')


rgb = np.stack([samp(bm[..., c]) for c in range(3)], 1)
wat = np.clip(samp(water), 0, 1)[:, None]
shd = samp(shade)[:, None]
cld = samp(cloud)

# land: lift the dark Blue Marble, add relief
lum = rgb.mean(1, keepdims=True)
land = np.power(np.clip(rgb, 0, 1), 0.58)
land = lum ** 0 * (lum.mean() * 0 + 1) * land
l2 = land.mean(1, keepdims=True)
land = np.clip(l2 + (land - l2) * 1.35, 0, 1) * 1.22
land = land * shd
# ocean: turquoise, lighter over shallows
t = np.clip((lum - 0.03) / 0.30, 0, 1)
deep = np.array([0.07, 0.34, 0.66], np.float32)
shallow = np.array([0.20, 0.72, 0.84], np.float32)
ocean = deep * (1 - t) + shallow * t
col = land * (1 - wat) + ocean * wat

# lighting
Lv = np.array([-0.35, 0.45, 0.80], np.float32)
Lv /= np.linalg.norm(Lv)
nx, ny, nz = x[inside], y[inside], z[inside]
dif = np.clip(nx * Lv[0] + ny * Lv[1] + nz * Lv[2], 0, 1)[:, None]
inten = (0.72 + 0.42 * dif) * (0.78 + 0.22 * nz[:, None] ** 0.6)
col = col * inten

# clouds
c = np.clip((cld - 0.12) / 0.7, 0, 1) ** 1.15 * 0.82
cc = np.array([0.96, 0.98, 1.0], np.float32) * (0.82 + 0.28 * dif)
col = col * (1 - c[:, None]) + cc * c[:, None]

# atmosphere + warm rim light (upper right)
theta = np.arctan2(y, x)
th0 = np.radians(42)
w = np.clip(np.cos(theta - th0), 0, 1) ** 2.2
f = (1 - nz) ** 2.4
blue = np.array([0.35, 0.68, 1.0], np.float32)
warm = np.array([1.0, 0.62, 0.20], np.float32)
wi = w[inside][:, None]
col = col + f[:, None] * (blue * (1 - wi) * 0.95 + warm * wi * 1.25)
col = np.clip(col, 0, 1)

# outside glow
rim = np.maximum(r - 1.0, 0)
gb = np.exp(-rim / 0.030)[..., None] * 0.50 * blue
gw = (np.exp(-rim / 0.090) * np.clip(np.cos(theta - th0), 0, 1) ** 2.0)[..., None] * 0.95 * warm
glow = np.clip(gb + gw, 0, 1)
glow_a = np.clip(glow.max(-1), 0, 1)
glow_a = np.where(r >= 1.0, glow_a, 0)
glow_a = np.where(r > 1.35, 0, glow_a)

surf = np.zeros((N, N, 3), np.float32)
surf[inside] = col
disc_a = np.clip((1.0 - r) * R / 1.5 + 0.5, 0, 1)
disc_a = np.where(r > 1.02, 0, disc_a)
disc_a = np.where(inside | (r < 1.003), disc_a, 0)

glow_rgb_pm = glow * (glow_a[..., None] / np.maximum(glow.max(-1, keepdims=True), 1e-6))
glow_rgb_pm = np.where(glow.max(-1, keepdims=True) > 0, glow_rgb_pm, 0)
da = disc_a[..., None]
pm = surf * da + glow_rgb_pm * (1 - da)
alpha = da[..., 0] + glow_a * (1 - da[..., 0])
straight = np.where(alpha[..., None] > 1e-4, pm / np.maximum(alpha[..., None], 1e-4), 0)
out = np.dstack([np.clip(straight, 0, 1), np.clip(alpha, 0, 1)])
img = Image.fromarray((out * 255 + 0.5).astype(np.uint8), 'RGBA')
img.save('/home/claude/tex/globe.png')
img.save('/home/claude/tex/globe.webp', 'WEBP', quality=90, method=6)
prev = Image.new('RGBA', (N, N), (11, 11, 42, 255))
prev.alpha_composite(img)
prev.convert('RGB').resize((700, 700), Image.LANCZOS).save('/home/claude/tex/prev.png')


# where does Uzbekistan (Toshkent) land, as a share of the PNG
def scr(la, lo):
    p, l = np.radians(la), np.radians(lo)
    cosc = np.sin(lat0) * np.sin(p) + np.cos(lat0) * np.cos(p) * np.cos(l - lon0)
    px = np.cos(p) * np.sin(l - lon0)
    py = np.cos(lat0) * np.sin(p) - np.sin(lat0) * np.cos(p) * np.cos(l - lon0)
    return float(cosc), (N / 2 + px * R) / N, (N / 2 - py * R) / N


print('Tashkent visible/x/y', scr(41.3, 69.2))
import os
print(os.path.getsize('/home/claude/tex/globe.webp') // 1024, 'KB webp', os.path.getsize('/home/claude/tex/globe.png') // 1024, 'KB png')
