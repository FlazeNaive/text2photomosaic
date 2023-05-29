import torch
import numpy as np
from PIL import Image
import pydiffvg
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--target_image", help="path to target image", default="inputs/target.png"
)
args = parser.parse_args()

RESULTS_PATH = "../results/target/"

# Create folder for saving results
if not os.path.exists(RESULTS_PATH):
    print("Creating folder for saving results...")
    os.makedirs(RESULTS_PATH)

gamma = 2.2

target = Image.open(args.target_image)
target = (torch.from_numpy(np.array(target)).float() / 255.0) ** gamma
target = target[:, :, 3:4] * target[:, :, :3] + torch.ones(
    target.shape[0], target.shape[1], 3, device=pydiffvg.get_device()
) * (1 - target[:, :, 3:4])
target = target[:, :, :3]

discrete_target = torch.zeros(target.shape)
canvas_width, canvas_height = target.shape[0], target.shape[1]

for x in range(0, canvas_width, canvas_width // 10):
    for y in range(0, canvas_height, canvas_height // 10):
        discrete_target[
            x : x + canvas_width // 10, y : y + canvas_height // 10, :
        ] = torch.mean(
            target[x : x + canvas_width // 10, y : y + canvas_height // 10, :],
            dim=(0, 1),
            keepdim=True,
        )

pixel_loss = torch.sum((discrete_target - target) ** 2) / (canvas_width * canvas_height)
print("Pixel loss: {}".format(pixel_loss.item()))
Image.fromarray((discrete_target ** (1 / gamma) * 255).byte().cpu().numpy()).save(
    os.path.join(RESULTS_PATH, "discrete_target.png")
)
