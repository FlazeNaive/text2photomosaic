from math import degrees
import sys
import numpy as np
import cv2
import pydiffvg
import torch

sys.path.append("../demo/")
from my_shape import PolygonRect, RotationalShapeGroup
sys.path.append("../retrieve/")
from retriever import retrieve_API, load_images, train_model

class Tile:
    """
    class for storing the tile information
    """
    def __init__(self, shape, pos, rotate, translate, fill, matrix):
        self.shape = shape
        self.pos= pos
        self.rotate = rotate
        self.translate = translate
        self.fill = fill
        self.matrix = matrix


def replace_tile_image(canvas, image, tile, output_path="output/result.png"): 
    """
    function for replacing the tile generated by diffvg
    the tile is a rotatable rectangle, and the rotation center is the topleft corner of the canvas

    what we will do is perform the rotation but maintain the center of the tile

    canvas: the image to paint
    tile: shape(w, h), pos(x, y), rotate(theta), fill(color) 
    image: the image to replace the tile, is already in the shape of the tile
    """

    pos = tile.pos.tolist()
    angle = tile.rotate
    translation = tile.translate.tolist()

    mat = tile.matrix.detach().numpy()[0:2, :]

    print("\tPOS= ", pos, ": ", type(pos))
    print("\tANGLE= ", angle, ": ", type(angle))
    print("\tTRANS= ", translation, ": ", type(translation))
    print("\tMAT= ", mat, ": ", type(mat))
    print("\tSHAPE= ", image.shape, ": ", type(image.shape))

    rotation_centor = (0, 0)

    rot_mat = cv2.getRotationMatrix2D(rotation_centor, angle, 1.0)
    trans_mat = np.array([[1, 0, translation[0]], [0, 1, translation[1]]])
    trans_mat = rot_mat * trans_mat

    canvas_sized_image = np.zeros((canvas.shape[0], canvas.shape[1], 3), dtype=np.uint8)
    mask = np.zeros((canvas.shape[0], canvas.shape[1]), dtype=np.uint8)
    alpha = np.zeros((canvas.shape[0], canvas.shape[1]), dtype=np.double)

    for x in range(image.shape[0]):
        for y in range(image.shape[1]):
            try:
                # cur_pos = (x + pos[0], y + pos[1])
                cur_pos = (x + pos[1], y + pos[0])
                canvas_sized_image[cur_pos] = image[x, y] 
                mask[cur_pos] = 255
                # alpha[cur_pos] = min(1.0, tile.fill[3].item())
                alpha[cur_pos] = 1.0
            except:
                pass


    result = cv2.warpAffine(canvas_sized_image, mat, canvas_sized_image.shape[1::-1], flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(mask, mat, canvas_sized_image.shape[1::-1], flags=cv2.INTER_LINEAR)
    alpha = cv2.warpAffine(alpha , mat, canvas_sized_image.shape[1::-1], flags=cv2.INTER_LINEAR)
    
    # cv2.imwrite("output/rotated_img.png", result)

    for x in range(result.shape[0]):
        for y in range(result.shape[1]):
            try:
                if mask[x, y] == 255:
                    canvas[x, y] = (result[x, y] * alpha[x, y] + canvas[x, y] * (1 - alpha[x, y])).astype(np.uint8)
            except:
                pass

    print("WRITING")
    # cv2.imwrite("output/result.png", canvas)
    cv2.imwrite(output_path, canvas)
    print("DONE")
    return canvas



def read_tiles(shapes, rotation_groups):
    """
    shapes: List[PolygonRect], the size and position of the tiles
    rotation_group: List[RotationalShapeGroup], the rotation of the tiles
    """
    tiles = []
    for (id, shape) in enumerate(shapes):
        print("\nID: ", id)
        print("\tTILE_SHAPE_ORIGIN: ", shape.size)
        print("\tTILE_SHAPE_DELTA: ", shape.delta*shape.coe_delta)
        print("\tPOS: ", shape.upper_left)
        print("\tFILL: ", rotation_groups[id].fill_color)
        tiles.append(Tile( shape.size + shape.delta * shape.coe_delta, 
                        #   shape.size * (shape.delta + torch.tensor([2, 2])) * torch.tensor([1, 2]),
                          shape.upper_left, 
                          degrees(rotation_groups[id].angle), 
                          rotation_groups[id].translation, rotation_groups[id].color,
                          rotation_groups[id].shape_to_canvas))
    
    # input("Press Enter to continue...")
    return tiles

#==================== test function ====================
def prepare_model(MODELPATH, IMAGEPATH, algorithm='kdtree'):
    """ return retrieve model and imageset, according to given paths

    Args:
        MODELPATH (str): path to retrieve model, if not exist, will train one
        IMAGEPATH (str): path to image dataset
        algorithm (str, optional): algorithm used by retriever. Defaults to 'kdtree'.

    Returns:
        (_type_, _type_): retrieve model, and corresponding imageset
    """
    import pickle
    import os
    print("Start preparing model...")
    if os.path.exists(MODELPATH):
        print("Model already exists, loading...")
        model = pickle.load(open(MODELPATH, "rb"))
    else:
        model = train_model(images, algorithm='kdtree')

    images = load_images(IMAGEPATH)
    print("Done preparing model...")
    return model, images

def read(shapes_file, shape_groups_file):
    """ return list of tiles, according to provided pkl files of shapes and shape_groups

    Args:
        shapes_file (str): path of shapes file (.pkl)
        shape_groups_file (str): path of shape_groups file (.pkl)

    Returns:
        List[Tile]: information of given tiles, unpacked from shapes/shape_groups file
    """
    import pickle
    print("Start reading...")
    with open(shapes_file, "rb") as fp:   # Unpickling
        shapes = pickle.load(fp)
    with open(shape_groups_file, "rb") as fp:   # Unpickling
        shape_groups = pickle.load(fp)

    tiles = read_tiles(shapes, shape_groups)
    return tiles

def paint(tiles, model, images, canvas_size = (224, 224, 3), name = "result.png"):
    """ replace tiles with retrieved images and save the generated photomosaic image

    Args:
        tiles (List[Tile]): list of tiles to replace
        model (_type_): image retrieve model
        images (_type_): image set for generateing photomosaic
        canvas_size (tuple, optional): size of canvas. Defaults to (224, 224, 3).
        name (str, optional): filename of generated image. Defaults to "result.png".

    Returns:
        tuple: generated photomosaic image
    """
    canvas = np.zeros(canvas_size, dtype=np.uint8)
    for id, tile in enumerate(tiles):
        tile_shape = tile.shape.int().tolist()
        tile_color = tile.fill.double().tolist()[0:3]
        tile_color = [int(x * 255) for x in tile_color]
        tile_color = [tile_color[2], tile_color[1], tile_color[0]]
        tile_color = [max(0, min(x, 255)) for x in tile_color]

        tile_color = [tile_color[2], tile_color[1], tile_color[0]]
        tile_img = np.asarray(retrieve_API(tile_color, tile_shape, model, images)) #, 'kdtree'))
        tile_img = cv2.resize(tile_img, (tile_shape))
        tile_img = cv2.cvtColor(tile_img, cv2.COLOR_BGR2RGB)
        color_img = np.zeros((tile_img.shape[0], tile_img.shape[1], 3), dtype=np.uint8)
        color_img[:] = tile_color
        color_img.dtype = np.uint8
        # tile_img[:] = 0.85 * tile_img + 0.15 * color_img
        # cv2.imwrite("output/tile_{}.png".format(id), tile_img)
        # cv2.imwrite("output/color_{}.png".format(id), color_img)
        print("COLOR: ", tile_color)
        # replace_tile_image(canvas, color_img, tile, output_path="output/" + name)
        replace_tile_image(canvas, tile_img, tile, output_path="results/photomosaic/" + name)
        # input("Press Enter to continue...")
    return canvas
    
def test_read():
    print("TEST READ")
    read_id = 1
    with open("../demo/tmp_files/shapes_{}.lp".format(read_id), "rb") as fp:   # Unpickling
        shapes = pickle.load(fp)
    with open("../demo/tmp_files/shape_groups_{}.lp".format(read_id), "rb") as fp:   # Unpickling
        shape_groups = pickle.load(fp)

    model = pickle.load(open("../retrieve/model.pkl", "rb"))
    images = load_images("../retrieve/content/images")

    tiles = read_tiles(shapes, shape_groups)

    canvas = np.zeros((224, 224, 3), dtype=np.uint8)

    for id, tile in enumerate(tiles):
        # print("\nID: ", id)
        # print("\tTILE_SHAPE_ORIGIN: ", tile.shape)
        # print("\tPOS: ", tile.pos)
        # print("\tROTATE: ", tile.rotate)
        # print("\tFILL: ", tile.fill)

        tile_shape = tile.shape.int().tolist()
        # tile.shape: (width, height)

        tile_color = tile.fill.double().tolist()[0:3]
        tile_color = [int(x * 255) for x in tile_color]
        tile_color = [tile_color[2], tile_color[1], tile_color[0]]
        tile_color = [max(0, min(x, 255)) for x in tile_color]
        # print("COLOR:", tile_color)

        tile_img = np.asarray(retrieve_API(tile_color, tile_shape, model, images)) #, 'kdtree'))
        tile_img = cv2.resize(tile_img, (tile_shape))
        # cv2.imwrite("output/tile_{}.png".format(id), tile_img)

        color_img = np.zeros((tile_img.shape[0], tile_img.shape[1], 3), dtype=np.uint8)
        color_img[:] = tile_color
        tile_img[:] = 0.85 * tile_img + 0.15 * color_img

        # KKKK = input("PRESS ENTER TO CONTINUE")

        replace_tile_image(canvas, tile_img, tile)


def test_rotate_image(canvas, tile):
    print("TEST ROTATE IMAGE")
    
    tile_img = cv2.resize(cv2.imread("target.png"), (tile.shape[0], tile.shape[1]))

    # rotate the tile
    tile_img = replace_tile_image(canvas, tile_img, tile)
    cv2.imwrite("output/result.png", tile_img)


# test function replaceTile
if __name__ == "__main__":

    # test_read()
    model, images = prepare_model("../retrieve/model.pkl", "../retrieve/dataset_demo")
    PATHPKL = "../demo/results/pkl/"
    tiles = read(PATHPKL + "shapes.pkl", PATHPKL + "shape_groups.pkl")
    canvas = paint(tiles, model, images, canvas_size = (224, 224, 3), name = "result.png")

