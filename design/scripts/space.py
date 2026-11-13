import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter

D = '/home/claude/tex/x/package/example/'
OUT = '/home/claude/tex/'
rng = np.random.default_rng(7)

# ---------- starfield ----------
SW, SH = 2400, 1500


def noise(h, w, sigma):
    return gaussian_filter(rng.standard_normal((h, w)).astype(np.float32), sigma)


def norm(a):
    a = a - a.min()
    return a / a.max()


yy, xx = np.mgrid[0:SH, 0:SW].astype(np.float32)
# Milky Way band, from upper left to the right middle
d = ((yy - SH * 0.05) - (xx * 0.38)) / SH
band = np.exp(-(d / 0.17) ** 2)
n1 = norm(noise(SH, SW, 90) + 0.6 * noise(SH, SW, 35) + 0.3 * noise(SH, SW, 12))
dust = norm(noise(SH, SW, 22) + 0.5 * noise(SH, SW, 7))
glow = band * (0.35 + 0.65 * n1) * np.clip(1.15 - dust * 0.9, 0.15, 1)
neb_v = norm(noise(SH, SW, 220)) ** 3
neb_t = norm(noise(SH, SW, 260)) ** 3

base = np.array([0.012, 0.016, 0.034], np.float32)
img = np.ones((SH, SW, 3), np.float32) * base
img += glow[..., None] * np.array([0.150, 0.140, 0.175], np.float32)
img += neb_v[..., None] * np.array([0.150, 0.045, 0.190], np.float32)
img += neb_t[..., None] * np.array([0.010, 0.095, 0.130], np.float32)


def add_stars(n, bmin, bmax, sigma, density=None):
    global img
    layer = np.zeros((SH, SW, 3), np.float32)
    if density is None:
        ys = rng.integers(0, SH, n)
        xs = rng.integers(0, SW, n)
    else:
        p = (density / density.sum()).ravel()
        idx = rng.choice(SH * SW, n, p=p)
        ys, xs = np.divmod(idx, SW)
    b = bmin + (bmax - bmin) * rng.random(n) ** 3.5
    t = rng.random(n)
    col = np.where(t[:, None] < 0.18, [0.75, 0.85, 1.0], np.where(t[:, None] > 0.88, [1.0, 0.86, 0.70], [1.0, 0.98, 0.95]))
    np.add.at(layer, (ys, xs), col * b[:, None])
    if sigma:
        layer = gaussian_filter(layer, (sigma, sigma, 0)) * (2 * np.pi * sigma ** 2)
    img += layer


dens = 0.25 + 2.2 * glow
add_stars(26000, 0.04, 0.55, 0.0, dens)
add_stars(5000, 0.10, 0.9, 0.6, dens)
add_stars(500, 0.35, 1.6, 0.85)
# a few bright stars with a soft halo
bright = np.zeros((SH, SW, 3), np.float32)
for _ in range(26):
    y, x = rng.integers(40, SH - 40), rng.integers(40, SW - 40)
    c = [0.8, 0.9, 1.0] if rng.random() < 0.5 else [1.0, 0.92, 0.82]
    bright[y, x] = np.array(c) * (2.5 + 5 * rng.random())
img += gaussian_filter(bright, (0.9, 0.9, 0)) * 6 + gaussian_filter(bright, (6, 6, 0)) * 3.5
# vignette
vg = 1 - 0.35 * (((xx / SW - 0.45) ** 2 + (yy / SH - 0.45) ** 2) / 0.5)
img *= vg[..., None]
img = np.clip(img, 0, 1) ** (1 / 1.05)
Image.fromarray((img * 255 + 0.5).astype(np.uint8)).save(OUT + 'stars.webp', 'WEBP', quality=86, method=6)
Image.fromarray((img * 255 + 0.5).astype(np.uint8)).resize((1200, 750), Image.LANCZOS).save(OUT + 'stars_prev.png')

# ---------- Earth from orbit ----------
W, H = 4096, 2048
day = np.asarray(Image.open(D + 'img/earth-blue-marble.jpg').convert('RGB'), np.float32) / 255
night = np.asarray(Image.open(D + 'img/earth-night.jpg').convert('RGB').resize((W, H), Image.BICUBIC), np.float32) / 255
water = np.asarray(Image.open(D + 'img/earth-water.png').convert('L').resize((W, H), Image.BILINEAR), np.float32) / 255
cloud = np.asarray(Image.open(D + 'clouds/clouds.png').convert('RGBA'), np.float32)[..., 3] / 255

L = np.array([-0.90, 0.14, -0.08], np.float32)
L /= np.linalg.norm(L)
TARGET = (-0.33, 0.68)
UZ = (41.3, 64.5)


def project(la, lo, lat0, lon0):
    p, l, a, b = map(np.radians, (la, lo, lat0, lon0))
    px = np.cos(p) * np.sin(l - b)
    py = np.cos(a) * np.sin(p) - np.sin(a) * np.cos(p) * np.cos(l - b)
    return px, py


best = None
for lat0 in np.arange(-20, 40, 0.5):
    for lon0 in np.arange(60, 130, 0.5):
        px, py = project(*UZ, lat0, lon0)
        e = (px - TARGET[0]) ** 2 + (py - TARGET[1]) ** 2
        if best is None or e < best[0]:
            best = (e, lat0, lon0)
_, LAT0, LON0 = best
print('view center', LAT0, LON0, 'err', best[0])

S = 1292  # disc radius in px
U0, U1, V0, V1 = -1.12, 0.263, 0.2105, 1.12
BW, BH = int((U1 - U0) * S), int((V1 - V0) * S)
gy, gx = np.mgrid[0:BH, 0:BW].astype(np.float32)
x = U0 + (gx + 0.5) / S
y = V1 - (gy + 0.5) / S
r2 = x * x + y * y
r = np.sqrt(r2)
inside = r2 < 1
z = np.sqrt(np.clip(1 - r2, 0, 1))
a, b = np.radians(LAT0), np.radians(LON0)
phi = np.arcsin(np.clip(z * np.sin(a) + y * np.cos(a), -1, 1))
lam = b + np.arctan2(x, z * np.cos(a) - y * np.sin(a))
u = ((np.degrees(lam) + 180) % 360) / 360 * W
v = (90 - np.degrees(phi)) / 180 * H
co = [v[inside], u[inside]]


def samp(arr):
    return map_coordinates(arr, co, order=1, mode='grid-wrap')


dc = np.stack([samp(day[..., i]) for i in range(3)], 1)
nc = np.stack([samp(night[..., i]) for i in range(3)], 1)
wt = samp(water)[:, None]
cl = samp(cloud)
nx, ny, nz = x[inside], y[inside], z[inside]
mu = nx * L[0] + ny * L[1] + nz * L[2]
dayw = np.clip((mu + 0.06) / 0.22, 0, 1)[:, None]  # soft terminator
lit = np.clip(mu, 0, 1)[:, None]

# natural day colours: mild lift, no extra saturation
land = np.clip(dc, 0, 1) ** 0.92 * 1.12
lm = land.mean(1, keepdims=True)
land = np.clip(lm + (land - lm) * 1.12, 0, 1)
ocean = dc * 0.85 + np.array([0.0, 0.015, 0.035])
surf = land * (1 - wt) + ocean * wt
c = np.clip((cl - 0.10) / 0.75, 0, 1) ** 1.2 * 0.9
surf = surf * (1 - c[:, None]) + np.array([0.93, 0.95, 0.98]) * c[:, None]
spec = (np.clip(mu, 0, 1) ** 1) * wt[:, 0] * np.exp(-((nx - L[0] * 0.6) ** 2 + (ny - L[1] * 0.6) ** 2) / 0.05) * 0.12
dayc = surf * (0.04 + 1.25 * lit ** 0.8) + spec[:, None]
# night lights
lights = np.clip(nc.max(1, keepdims=True) * (nc[:, :1] > nc[:, 2:3]) - 0.10, 0, 1) ** 1.3 * np.array([1.0, 0.78, 0.48]) * 1.6 * (1 - c[:, None] * 0.7)
nightc = surf * 0.025 + lights
col = dayc * dayw + nightc * (1 - dayw)
# atmosphere: thin blue limb on the day side, warm near the terminator
f = (1 - nz) ** 3.0
term = np.exp(-(mu / 0.18) ** 2)
atm = f[:, None] * (np.clip(mu + 0.25, 0, 1)[:, None] * np.array([0.30, 0.55, 1.0]) * 1.1 + term[:, None] * np.array([1.0, 0.55, 0.25]) * 0.7)
col = col + atm
col = col / (1 + 0.18 * col)

out = np.zeros((BH, BW, 4), np.float32)
out[inside, :3] = col
edge = np.clip((1 - r) * S + 0.5, 0, 1)
out[..., 3] = np.where(inside, edge, 0)

# outer atmosphere glow beyond the limb
th = np.arctan2(y, x)
lim_mu = np.clip(np.cos(th) * L[0] + np.sin(th) * L[1], -1, 1)  # how sunlit that limb point is
h = np.maximum(r - 1, 0)
ga = np.exp(-h / 0.012) * 0.85 + np.exp(-h / 0.05) * 0.22
ga *= np.clip(lim_mu * 0.9 + 0.35, 0, 1)
warm = np.exp(-((lim_mu - 0.05) / 0.25) ** 2)
gcol = np.array([0.40, 0.66, 1.0])[None, None] * (1 - warm[..., None]) + np.array([1.0, 0.62, 0.32])[None, None] * warm[..., None]
outside = r >= 1
a_out = np.clip(ga, 0, 1) * outside
alpha = out[..., 3] + a_out * (1 - out[..., 3])
rgb = (out[..., :3] * out[..., 3:4] + gcol * a_out[..., None] * (1 - out[..., 3:4])) / np.maximum(alpha[..., None], 1e-4)
fin = np.dstack([np.clip(rgb, 0, 1), np.clip(alpha, 0, 1)])
eimg = Image.fromarray((fin * 255 + 0.5).astype(np.uint8), 'RGBA')
eimg.save(OUT + 'earth.webp', 'WEBP', quality=88, method=6)

st = Image.open(OUT + 'stars.webp').convert('RGBA').resize((1440, 900))
ew = round(1440 * (U1 - U0) * 760 / 1440)
eh = round((V1 - V0) * 760)
st.alpha_composite(eimg.resize((ew, eh), Image.LANCZOS), (1440 - ew, 900 - eh))
st.convert('RGB').save(OUT + 'comp_prev.png')
px, py = project(*UZ, LAT0, LON0)
print('box', BW, BH, 'UZ local', px, py, 'UZ in box %', (px - U0) / (U1 - U0) * 100, (V1 - py) / (V1 - V0) * 100)
print('Tashkent', [(float(q)) for q in project(41.3, 69.24, LAT0, LON0)])
import os
print({k: os.path.getsize(OUT + k) // 1024 for k in ['stars.webp', 'earth.webp']})
