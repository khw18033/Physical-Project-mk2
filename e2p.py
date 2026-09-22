import sys, numpy as np, py360convert
from PIL import Image

src, out, u, v = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
equ = np.array(Image.open(src))
persp = py360convert.e2p(equ, fov_deg=(90,90), u_deg=u, v_deg=v,
                         out_hw=(720,720))
Image.fromarray(persp).save(out)
print("저장:", out)