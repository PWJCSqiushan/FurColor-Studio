# Third-party notices

FurColor Studio's original application code is released under Apache-2.0. Optional models, model-derived materials and runtime frameworks retain their own licenses. The Apache-2.0 badge does not replace those terms. Anyone redistributing a combined commercial package should review the included licenses and obtain any additional license required for their use case; this notice is not legal advice.

## OpenCV YuNet face detector

FurColor Studio can download `face_detection_yunet_2023mar.onnx` from the official OpenCV Zoo repository during local setup. The model is not committed to this repository.

- Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- Pinned file commit: `f12e12798e8314f7c074a6656816c048dcc95b7a`
- SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- File size: `232589` bytes
- License: MIT License, as declared by the OpenCV Zoo YuNet directory

The installer refuses the download if the SHA-256 does not match.

## Fursee

The optional V4 subject-intelligence adapter interoperates with Fursee, created by Jundi Wu and published from Shandong University.

- Repository: https://github.com/lionking0921/fursee
- Paper: https://arxiv.org/abs/2606.22872
- Adapter reference commit: `f7404dbfa9702f2a724868830a58f35c9338a590`
- Model-package source supplied by the user: https://pan.quark.cn/s/c6f4b595d67e
- License copy: [`licenses/FURSEE-LICENSE.md`](licenses/FURSEE-LICENSE.md)

FurColor does not redistribute Fursee weights. `install_fursee.ps1` references a user-supplied local package and checks the following pinned files before use:

| File | Bytes | SHA-256 |
|---|---:|---|
| `cut.pt` | 53,034,334 | `a3887f138f5ec32b7e8838bf26943aa747818991257c443ff9befdf19ec38e20` |
| `model.safetensors` | 1,215,728,808 | `1ffd6614ed85a57d288ad90766a405653263488e2f1b25e99e3f6b76abe21197` |
| `config.json` | 777 | `5fb4859cf4ee4055b7861a620e0b7741cdb1e21b81bfbe67e921475219a781ce` |
| `preprocessor_config.json` | 407 | `78645f94efe99131db72b562cc8537566194039dfddfdcfff32b2bf6c41db423` |

Fursee's license requires attribution and carries privacy, downstream-distribution and commercial-use conditions. Preserve the license copy and upstream attribution.

## Ultralytics YOLO

The optional detector is loaded through `ultralytics==8.4.60`, and the supplied `cut.pt` identifies a YOLO26l architecture. Ultralytics' open-source distribution uses AGPL-3.0, with separate enterprise licensing offered by its vendor. A copy supplied alongside the Fursee package is retained at [`licenses/YOLO-LICENSE.txt`](licenses/YOLO-LICENSE.txt). Users are responsible for determining whether their deployment or commercial distribution requires different licensing.

- Framework: https://github.com/ultralytics/ultralytics
- License copy: [`licenses/YOLO-LICENSE.txt`](licenses/YOLO-LICENSE.txt)

## DINOv3

The optional embedding model is an ArcFace-optimized DINOv3 ViT-L/16 derivative. DINOv3 base materials retain their upstream terms. The license copy supplied with the Fursee package is retained at [`licenses/DINOV3-LICENSE.md`](licenses/DINOV3-LICENSE.md).

- Upstream: https://github.com/facebookresearch/dinov3
- License copy: [`licenses/DINOV3-LICENSE.md`](licenses/DINOV3-LICENSE.md)

## Runtime libraries

The optional environment pins PyTorch 2.7.1 + CUDA 12.8, torchvision 0.22.1, Transformers 4.56.0, Safetensors 0.6.2 and their dependencies. Their copyright and license terms remain with their respective projects. Dependency installation occurs locally from the configured Python package indexes; packages are not vendored into this repository.