from subprocess import call
import pydiffvg
import torch
from my_shape import PolygonRect, RotationalShapeGroup
from utils import diffvg_regularization_term, pairwise_diffvg_regularization_term
import optuna
from torch.optim.lr_scheduler import StepLR
import pickle
import numpy as np
from PIL import Image
import os

# Load the best parameters
if os.path.exists("target_best_params.pkl"):
    print("Loading best parameters...")
    best_params = pickle.load(open("target_best_params.pkl", "rb"))
    print("Best parameters: ")
    print(best_params)

    delta_lr = best_params["delta_lr"]
    angle_lr = best_params["angle_lr"]
    tranlation_lr = best_params["tranlation_lr"]
    color_lr = best_params["color_lr"]

    coe_delta = torch.tensor(
        [best_params["reg_delta_coe_x"], best_params["reg_delta_coe_y"]],
        dtype=torch.float32,
    )
    coe_displacement = torch.tensor(
        [best_params["reg_displacement_coe_x"], best_params["reg_displacement_coe_y"]],
        dtype=torch.float32,
    )
    coe_angle = torch.tensor(best_params["angle_coe"], dtype=torch.float32)

    coe_overlap = torch.tensor(best_params["overlap_coe"], dtype=torch.float32)

    num_neighbor = best_params["neighbor_num"]
    coe_neighbor = torch.tensor(best_params["neighbor_coe"], dtype=torch.float32)
else:
    print("No best parameters found, using default parameters...")
    delta_lr = 0.01
    angle_lr = 0.01
    tranlation_lr = 0.01
    color_lr = 0.01

    coe_delta = torch.tensor([1e-4, 1e-4], dtype=torch.float32)
    coe_displacement = torch.tensor([1e-4, 1e-4], dtype=torch.float32)
    coe_angle = torch.tensor(1e-4, dtype=torch.float32)

    coe_overlap = torch.tensor(0.0, dtype=torch.float32)

    num_neighbor = 1
    coe_neighbor = torch.tensor(0.0, dtype=torch.float32)

# Use GPU if available
pydiffvg.set_use_gpu(torch.cuda.is_available())

gamma = 2.2
render = pydiffvg.RenderFunction.apply

# Load target image
target = Image.open("target.png")
target = (torch.from_numpy(np.array(target)).float() / 255.0) ** gamma
target = target[:, :, 3:4] * target[:, :, :3] + torch.ones(
    target.shape[0], target.shape[1], 3, device=pydiffvg.get_device()
) * (1 - target[:, :, 3:4])
target = target[:, :, :3]
canvas_width, canvas_height = target.shape[1], target.shape[0]

# Initializations
shapes = []
shape_groups = []
for x in range(0, canvas_width, canvas_width // 10):
    for y in range(0, canvas_height, canvas_height // 10):
        rect = PolygonRect(
            upper_left=torch.tensor([x, y]),
            width=canvas_width // 10 + 0.0,
            height=canvas_height // 10 + 0.0,
        )
        shapes.append(rect)
        rect_group = RotationalShapeGroup(
            shape_ids=torch.tensor([len(shapes) - 1]),
            fill_color=torch.cat([torch.rand(3), torch.tensor([1.0])]),
            transparent=False,
            coe_ang=torch.tensor(1.0),
            coe_trans=torch.tensor([canvas_width, canvas_height], dtype=torch.float32),
        )
        shape_groups.append(rect_group)

for rect in shapes:
    rect.update()
for rect_group in shape_groups:
    rect_group.update()

scene_args = pydiffvg.RenderFunction.serialize_scene(
    canvas_width, canvas_height, shapes, shape_groups
)
img = render(
    canvas_width,  # width
    canvas_height,  # height
    2,  # num_samples_x
    2,  # num_samples_y
    1,  # seed
    None,  # background_image
    *scene_args
)
pydiffvg.imwrite(img.cpu(), "results/target/init.png", gamma=gamma)

optimizer_delta = torch.optim.Adam([rect.delta for rect in shapes], lr=delta_lr)
optimizer_angle = torch.optim.Adam(
    [rect_group.angle for rect_group in shape_groups], lr=angle_lr
)
optimizer_translation = torch.optim.Adam(
    [rect_group.translation for rect_group in shape_groups], lr=tranlation_lr
)
optimizer_color = torch.optim.Adam(
    [rect_group.color for rect_group in shape_groups], lr=color_lr
)

num_interations = 1000
scheduler_delta = StepLR(optimizer_delta, step_size=num_interations // 3, gamma=0.5)
scheduler_angle = StepLR(optimizer_angle, step_size=num_interations // 3, gamma=0.5)
scheduler_translation = StepLR(
    optimizer_translation, step_size=num_interations // 3, gamma=0.5
)
scheduler_color = StepLR(optimizer_color, step_size=num_interations // 3, gamma=0.5)

# Run optimization iterations.
for t in range(num_interations):
    print("iteration:", t)

    optimizer_delta.zero_grad()
    optimizer_angle.zero_grad()
    optimizer_translation.zero_grad()
    optimizer_color.zero_grad()

    for rect in shapes:
        rect.update()
    for rect_group in shape_groups:
        rect_group.update()

    scene_args = pydiffvg.RenderFunction.serialize_scene(
        canvas_width, canvas_height, shapes, shape_groups
    )
    img = render(
        canvas_width,  # width
        canvas_height,  # height
        2,  # num_samples_x
        2,  # num_samples_y
        t + 1,  # seed
        None,  # background_image
        *scene_args
    )

    # Save the intermediate render.
    if t % 5 == 0:
        pydiffvg.imwrite(
            img.cpu(), "results/target/iter_{}.png".format(t // 5), gamma=gamma
        )

    # Pixel-wise loss.
    img = img[:, :, 3:4] * img[:, :, :3] + torch.ones(
        img.shape[0], img.shape[1], 3, device=pydiffvg.get_device()
    ) * (1 - img[:, :, 3:4])
    img = img[:, :, :3]
    pixel_loss = torch.sum((img - target) ** 2) / (canvas_width * canvas_height)

    # Regularization term
    diffvg_regularization_loss = diffvg_regularization_term(
        shapes,
        shape_groups,
        coe_delta=coe_delta,
        coe_displacement=coe_displacement,
        coe_angle=coe_angle,
    )
    pairwise_diffvg_regularization_loss = pairwise_diffvg_regularization_term(
        shapes,
        shape_groups,
        coe_overlap=coe_overlap,
        num_neighbor=num_neighbor,
        coe_neighbor=coe_neighbor,
    )
    loss = pixel_loss + diffvg_regularization_loss + pairwise_diffvg_regularization_loss

    print("pixel_loss:", pixel_loss.item())
    print("diffvg_regularization_loss:", diffvg_regularization_loss.item())
    print(
        "pairwise_diffvg_regularization_loss:",
        pairwise_diffvg_regularization_loss.item(),
    )
    print("loss:", loss.item())

    # Backpropagate the gradients.
    loss.backward(retain_graph=True)

    # Take a gradient descent step.
    optimizer_delta.step()
    optimizer_angle.step()
    optimizer_translation.step()
    optimizer_color.step()

    # Take a scheduler step in the learning rate.
    scheduler_delta.step()
    scheduler_angle.step()
    scheduler_translation.step()
    scheduler_color.step()

# Render the final result.
scene_args = pydiffvg.RenderFunction.serialize_scene(
    canvas_width, canvas_height, shapes, shape_groups
)
img = render(
    canvas_width,  # width
    canvas_height,  # height
    2,  # num_samples_x
    2,  # num_samples_y
    102,  # seed
    None,  # background_image
    *scene_args
)
# Save the images and differences.
pydiffvg.imwrite(img.cpu(), "results/target/final.png", gamma=gamma)

# Convert the intermediate renderings to a video.
call(
    [
        "ffmpeg",
        "-framerate",
        "24",
        "-i",
        "results/target/iter_%d.png",
        "-vb",
        "20M",
        "results/target/out.mp4",
    ]
)
