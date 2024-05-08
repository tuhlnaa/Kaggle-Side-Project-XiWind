﻿import cv2
import h5py
import torch
import numpy as np
import matplotlib.pyplot as plt

from PIL import Image
from torchvision import transforms


def depth_norm(depth, max_depth=1000.0):
	return (max_depth / depth).to(torch.float32)


def load_image(file_path):
	img = Image.open(file_path).convert('L')  # Convert to grayscale
	transform = transforms.ToTensor()
	return transform(img).unsqueeze(0)        # Add batch dimension


def load_data(filepath, tensor_format=False):
	"""
	Load image and depth map data from an H5 file.

	Parameters:
	- filepath (str): The path to the H5 file containing the data.
	- tensor_format (bool): If True, outputs data as PyTorch tensors with additional dimension for batch size.
	  If False, outputs data as NumPy arrays.

	Returns:
	- tuple: A tuple containing the images and depth maps. If tensor_format is True,
	  images will have shape (1, 3, h, w) and depth_maps will have shape (1, 1, h, w) as PyTorch tensors.
	  If tensor_format is False, images will have shape (3, h, w) and depth_maps will have shape (h, w) as NumPy arrays.
	"""
	with h5py.File(filepath, 'r') as file:
		# Get keys assuming the first key is for depth maps and the second key is for images
		keys = list(file.keys())
		depth_maps_out = np.array(file[keys[0]])
		images = np.array(file[keys[1]])
		images_out = np.transpose(images, (1, 2, 0))  # Change (C, H, W) to (H, W, C)
		
		# Check if output should be in tensor format
		if tensor_format:
			# Convert arrays to PyTorch tensors and add a batch dimension
			images_out = torch.from_numpy(images).unsqueeze(0)
			depth_maps_out = torch.from_numpy(depth_maps_out).unsqueeze(0).unsqueeze(0)
		return images_out, depth_maps_out


def show_image(image_array, title="Image"):
	# Display an image
	plt.figure()
	plt.imshow(image_array)
	plt.title(title)
	plt.axis('off')
	plt.show()


def show_depth_map(depth_map, title="Depth Map"):
	# Display a depth map
	plt.figure()
	plt.imshow(depth_map, cmap='viridis', vmax=1, vmin=0)
	plt.title(title)
	plt.colorbar()
	plt.axis('off')
	plt.show()


class AverageMeter(object):
	def __init__(self):
		self.reset()

	def reset(self):
		self.val = 0
		self.avg = 0
		self.sum = 0
		self.count = 0

	def update(self, val, n=1):
		self.val = val
		self.sum += val * n
		self.count += n
		self.avg = self.sum / self.count


def apply_colormap(tensor, min_val=10, max_val=1000, colormap='viridis'):
	"""
	Applies a colormap to a 4-channel (b, 1, h, w) tensor and returns a 3-channel (b, 3, h, w) image tensor.

	Parameters:
	min_val (float, optional): Minimum value for normalization. If None, uses the tensor's minimum value.
	max_val (float, optional): Maximum value for normalization. If None, uses the tensor's maximum value.
	colormap (str): The name of the colormap to use. Defaults to "binary" or "rainbow".
	
	Returns:
	torch.Tensor: A 3-channel (b, 3, h, w) image tensor.
	"""
	# Ensure tensor is on CPU and convert to NumPy array
	tensor = tensor.cpu().numpy()

	# Normalize the tensor
	# if min_val is None:
	# 	min_val = tensor.min()
	# if max_val is None:
	# 	max_val = tensor.max()
	# if min_val != max_val:
	# 	tensor = (tensor - min_val) / (max_val - min_val)
	# else:
	# 	tensor = np.zeros_like(tensor)

	# Apply colormap
	cm = plt.get_cmap(colormap)
	colored_image = cm(tensor.squeeze(1))  # Remove the channel dimension for colormapping
	
	# Drop the alpha channel and convert to RGB
	colored_image_rgb = colored_image[..., :3]
	
	# Convert back to PyTorch tensor and reorder dimensions to (b, c, h, w)
	depth = torch.from_numpy(colored_image_rgb)
	depth = depth.permute(0, 3, 1, 2)  # Change dimension order

	return depth


def load_from_checkpoint(ckpt, model, optimizer, epochs, loss_meter=None):
	checkpoint = torch.load(ckpt)
	ckpt_epoch = epochs - (checkpoint["epoch"] + 1)
	if ckpt_epoch <= 0:
		raise ValueError("Epochs provided: {}, epochs completed in ckpt: {}".format(epochs, 
			checkpoint["epoch"] + 1))

	model.load_state_dict(checkpoint["model_state_dict"])
	optimizer.load_state_dict(checkpoint["optim_state_dict"])

	return model, optimizer, ckpt_epoch


def init_or_load_model(depthmodel, enc_pretrain, epochs, lr, ckpt=None, device=torch.device("cuda:0"), 
	loss_meter=None):

	if ckpt is not None:
		checkpoint = torch.load(ckpt)

	model = depthmodel(encoder_pretrained=enc_pretrain)

	if ckpt is not None:
		model.load_state_dict(checkpoint["model_state_dict"])

	model = model.to(device)

	optimizer = torch.optim.Adam(model.parameters(), lr=lr)

	if ckpt is not None:
		optimizer.load_state_dict(checkpoint["optim_state_dict"])

	start_epoch = 0
	if ckpt is not None:
		start_epoch = checkpoint["epoch"] + 1

		if start_epoch <= 0:
			raise ValueError("Epochs provided: {}, epochs completed in ckpt: {}".format(epochs, 
				checkpoint["epoch"] + 1))

	return model, optimizer, start_epoch


def load_images(image_files):
	loaded_images = []

	for file in image_files:
		x = np.clip(np.asarray(Image.open(file).resize((640, 480)), dtype=float)/255, 0, 1).transpose(2, 0, 1)
		#x = np.clip(np.asarray(Image.open(file).resize((320, 240)), dtype=float)/255, 0, 1).transpose(2, 0, 1)
		loaded_images.append(x)

	return np.stack(loaded_images, axis=0)


def compute_depth_estimation_metrics(true_depth, predicted_depth):
	"""
	Compute error metrics for depth estimation using PyTorch.

	This function calculates several metrics commonly used to evaluate the quality of depth maps produced
	by depth estimation models, specifically focusing on transfer learning models for monocular depth estimation.

	Parameters:
	- true_depth (torch.Tensor): A ground truth depth map tensor of shape (B, 1, H, W).
	- predicted_depth (torch.Tensor): A predicted depth map tensor of the same shape as true_depth.

	Returns:
	- dict: A dictionary containing the computed metrics:
	  - 'a1': The percentage of predicted depth values within a threshold of 1.25 times the true depth values.
	  - 'a2': The percentage within 1.25^2 of the true values.
	  - 'a3': The percentage within 1.25^3 of the true values.
	  - 'abs_rel': The mean absolute relative error.
	  - 'rmse': The root mean square error.
	  - 'log_10': The mean log10 error.
	"""

	# Ensure the depth maps are flattened to simplify calculations
	true_depth = true_depth.view(-1)
	predicted_depth = predicted_depth.view(-1)

	# Calculate threshold scales
	threshold_ratio = torch.max(true_depth / predicted_depth, predicted_depth / true_depth)
	a1 = (threshold_ratio < 1.25).float().mean()
	a2 = (threshold_ratio < 1.25**2).float().mean()
	a3 = (threshold_ratio < 1.25**3).float().mean()

	# Calculate absolute relative error
	abs_rel = torch.mean(torch.abs(true_depth - predicted_depth) / true_depth)

	# Calculate RMSE
	rmse = torch.sqrt(torch.mean((true_depth - predicted_depth) ** 2))

	# Calculate mean log10 error
	log_10 = torch.mean(torch.abs(torch.log10(true_depth) - torch.log10(predicted_depth)))

	return {
		'a1': a1.item(),
		'a2': a2.item(),
		'a3': a3.item(),
		'abs_rel': abs_rel.item(),
		'rmse': rmse.item(),
		'log_10': log_10.item()
	}


def main():
	# 【load_data()】
	# Change 'yourfile.h5' to the path of your H5 file
	images, depth_maps = load_data('00186.h5', tensor_format=False)
	show_image(images)
	show_depth_map(depth_maps / 10)
	print(images.shape, depth_maps.shape)  # (480, 640, 3) (480, 640)

	# =========================================================
	# 【compute_depth_estimation_metrics()】
	images, depth_maps = load_data('00186.h5', tensor_format=True)
	metrics = compute_depth_estimation_metrics(depth_maps / 10, depth_maps / 10)
	print(metrics)
	
	# =========================================================
	# 【apply_colormap()】
	images, depth_maps = load_data('00186.h5', tensor_format=True)
	depth_colormap = apply_colormap(depth_maps / 10)
	depth_colormap = depth_colormap.permute(0, 2, 3, 1).numpy()  # Change from (b, c, h, w) to (b, h, w, c)
	show_image(depth_colormap[0]) 


if __name__ == "__main__":
	main()