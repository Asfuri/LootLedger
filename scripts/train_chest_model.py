"""Train a small local SSDLite chest-state model; export raw heads for OpenCV.

Training only: pip install torch torchvision onnx opencv-python-headless.
The desktop app uses ONNX Runtime and OpenCV with the exported model, never PyTorch.
"""
import argparse
from functools import partial
import hashlib
import json
from pathlib import Path
import random
import time

import cv2
import numpy as np
import torch
from torch import nn
from torchvision.models.detection import ssdlite320_mobilenet_v3_large
from torchvision.models.detection.ssdlite import SSDLiteClassificationHead
from torchvision.models.detection.image_list import ImageList
from torchvision.models.detection.anchor_utils import DefaultBoxGenerator


def build_model(size, pretrained):
    model = ssdlite320_mobilenet_v3_large(weights="DEFAULT" if pretrained else None,
        weights_backbone=None, trainable_backbone_layers=2)
    model.transform.fixed_size = (size, size)
    model.anchor_generator = DefaultBoxGenerator([[2, 3]] * 6,
        scales=[.07, .15, .30, .45, .60, .80, .95])
    model.eval()
    with torch.no_grad():
        channels = [x.shape[1] for x in model.backbone(torch.zeros(1, 3, size, size)).values()]
    model.head.classification_head = SSDLiteClassificationHead(channels,
        model.anchor_generator.num_anchors_per_location(), 3,
        partial(nn.BatchNorm2d, eps=.001, momentum=.03))
    return model


class Examples:
    def __init__(self, folder, size):
        self.size = size
        metadata = json.loads((folder / "annotations.json").read_text(encoding="utf-8"))
        self.crops = {state: [cv2.imread(str(folder / x["file"])) for x in metadata["crops"]
                              if x["state"] == state] for state in ("closed", "opened")}
        self.backgrounds = [cv2.imread(str(folder / x)) for x in metadata["backgrounds"]]
        self.scene_backgrounds = [cv2.imread(str(folder / x)) for x in metadata.get("scene_backgrounds", [])]
        self.frames = {state: [(cv2.imread(str(folder / x["file"])), x) for x in metadata.get("frames", [])
                               if x["state"] == state] for state in ("closed", "opened")}
        if any(x is None for values in self.crops.values() for x in values):
            raise ValueError("A training crop cannot be decoded")

    def sample(self):
        size = self.size
        if self.frames["closed"] and random.random() < .55:
            frame, annotation = random.choice(self.frames[random.choice(("closed", "opened"))])
            image, scale, left, top = letterbox(frame, size)
            boxes = np.array(annotation["boxes"], np.float32)
            boxes[:, [0, 2]] = boxes[:, [0, 2]] * scale + left
            boxes[:, [1, 3]] = boxes[:, [1, 3]] * scale + top
            if random.random() < .5:
                image = cv2.flip(image, 1)
                boxes[:, [0, 2]] = size - boxes[:, [2, 0]]
            tensor = torch.from_numpy(cv2.cvtColor(image, cv2.COLOR_BGR2RGB).copy()).permute(2, 0, 1).float() / 255
            return tensor, {"boxes": torch.from_numpy(boxes), "labels": torch.tensor(annotation["labels"], dtype=torch.int64)}
        backgrounds = self.scene_backgrounds if self.scene_backgrounds and random.random() < .8 else self.backgrounds
        image, _, _, _ = letterbox(random.choice(backgrounds), size)
        if random.random() < .35:
            image[:] = np.random.randint(10, 180, (1, 1, 3), dtype=np.uint8)
        boxes, labels = [], []
        for _ in range(random.choice((1, 1, 2))):
            state = random.choice(("closed", "opened"))
            crop = random.choice(self.crops[state]).copy()
            if random.random() < .5:
                crop = cv2.flip(crop, 1)
            height = random.randint(size // 12, size // 3)
            width = max(16, round(height * crop.shape[1] / crop.shape[0] * random.uniform(.8, 1.2)))
            width = min(size // 2, width)
            crop = cv2.resize(crop, (width, height))
            x, y = random.randint(0, size - width), random.randint(0, size - height)
            if any(min(x + width, b[2]) > max(x, b[0]) and min(y + height, b[3]) > max(y, b[1]) for b in boxes):
                continue
            image[y:y + height, x:x + width] = crop
            boxes.append([x, y, x + width, y + height])
            labels.append(1 if state == "closed" else 2)
        image = np.clip(image.astype(np.float32) * random.uniform(.65, 1.25)
                        + random.uniform(-15, 15), 0, 255).astype(np.uint8)
        if random.random() < .2:
            image = cv2.GaussianBlur(image, (3, 3), .5)
        tensor = torch.from_numpy(cv2.cvtColor(image, cv2.COLOR_BGR2RGB).copy()).permute(2, 0, 1).float() / 255
        return tensor, {"boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
                        "labels": torch.tensor(labels, dtype=torch.int64)}


def letterbox(frame, size):
    h, w = frame.shape[:2]
    scale = min(size / w, size / h)
    width, height = round(w * scale), round(h * scale)
    left, top = (size - width) // 2, (size - height) // 2
    image = np.full((size, size, 3), 114, np.uint8)
    image[top:top + height, left:left + width] = cv2.resize(frame, (width, height))
    return image, scale, left, top


class RawHeads(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.backbone, self.head = model.backbone, model.head
        self.register_buffer("mean", torch.tensor(model.transform.image_mean).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor(model.transform.image_std).view(1, 3, 1, 1))

    def forward(self, image):
        features = list(self.backbone((image - self.mean) / self.std).values())
        result = self.head(features)
        return result["bbox_regression"], result["cls_logits"]


def export(model, output, size, training):
    output.mkdir(parents=True, exist_ok=True)
    model.cpu().eval()
    sample = torch.zeros(1, 3, size, size)
    raw = RawHeads(model).eval()
    path = output / "chest-state.onnx"
    with torch.no_grad():
        features = list(model.backbone(sample).values())
        anchors = model.anchor_generator(ImageList(sample, [(size, size)]), features)[0].numpy()
        expected = [x.numpy() for x in raw(sample)]
    torch.onnx.export(raw, sample, str(path), input_names=["image"],
                      output_names=["boxes", "logits"], opset_version=17, dynamo=False)
    np.savez_compressed(output / "chest-anchors.npz", anchors=anchors)
    net = cv2.dnn.readNetFromONNX(str(path))
    net.setInput(sample.numpy())
    actual = net.forward(["boxes", "logits"])
    differences = [float(np.max(np.abs(a - b))) for a, b in zip(expected, actual)]
    if max(differences) > .02:
        raise RuntimeError(f"OpenCV export parity failed: {differences}")
    card = {"architecture": "TorchVision SSDLite MobileNetV3 Large, raw heads",
            "input_size": size, "classes": ["background", "closed", "opened"],
            "box_coder_weights": list(model.box_coder.weights),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license": "BSD-3-Clause (TorchVision); see MODEL-NOTICE.txt",
            "training": training, "independent_gameplay_validation": False,
            "limitations": "Small user-supplied training set of ornate gold chests. Other chest appearances, spectators and negative gameplay remain unvalidated. Automatic candidates require review.",
            "opencv_export_max_errors": differences}
    card["training_video_sha256"] = training.get("video_sha256", [])
    (output / "chest-model.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(json.dumps(card, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("local-data/chest-training"))
    parser.add_argument("--output", type=Path, default=Path("lootledger/assets"))
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    cv2.setNumThreads(1)
    torch.set_num_threads(2)
    random.seed(19)
    np.random.seed(19)
    torch.manual_seed(19)
    if args.device == "cuda":
        torch.cuda.set_per_process_memory_fraction(.30)
    model = build_model(args.size, pretrained=True).to(args.device)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=.0008, weight_decay=.0005)
    examples = Examples(args.data, args.size)
    start = time.monotonic()
    for step in range(args.steps):
        model.train()
        for module in model.modules():
            if isinstance(module, nn.BatchNorm2d):
                module.eval()
        batch = [examples.sample() for _ in range(args.batch)]
        images = [image.to(args.device) for image, _ in batch]
        targets = [{k: v.to(args.device) for k, v in target.items()} for _, target in batch]
        losses = model(images, targets)
        loss = sum(losses.values())
        if not torch.isfinite(loss):
            raise RuntimeError(f"Non-finite loss at step {step}")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10)
        optimizer.step()
        if step in (args.steps // 2, args.steps * 4 // 5):
            for group in optimizer.param_groups:
                group["lr"] *= .3
        if step % 25 == 0 or step == args.steps - 1:
            print(f"step {step + 1}/{args.steps} loss={float(loss.detach()):.4f} elapsed={time.monotonic() - start:.1f}s", flush=True)
    args.data.mkdir(parents=True, exist_ok=True)
    torch.save(model.cpu().state_dict(), args.data / "chest-state.pth")
    training = {"seed": 19, "steps": args.steps, "batch": args.batch,
                "training_annotations": str(args.data / "annotations.json"),
                "note": "Includes frames from supplied recording. A subsequent pass on that video is a regression, not a held-out accuracy result."}
    annotations = json.loads((args.data / "annotations.json").read_text(encoding="utf-8"))
    video = Path(annotations["video"])
    training["video_sha256"] = [hashlib.sha256(video.read_bytes()).hexdigest()] if video.is_file() else []
    export(model, args.output, args.size, training)
