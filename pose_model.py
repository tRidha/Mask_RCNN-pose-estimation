import os
import sys
import random
import math
from math import sin, cos
import numpy as np
import skimage.io
import matplotlib
import matplotlib.pyplot as plt
import csv
from squaternion import euler2quat, quat2euler, Quaternion

from PIL import ImageDraw, Image
import cv2

class_names = []
rcnn_model = 0 

IMAGE_PATH = '../dataset/images/'
MASK_PATH = '../dataset/masks/'

TRAIN_CSV = 'train_new.csv'
TEST_CSV = 'test_new.csv'

# --------------------------------------- MASK R CNN SETUP --------------------------------------- #
def init_maskrcnn():
  global class_names, rcnn_model
  # Root directory of the project
  ROOT_DIR = os.path.abspath("../")

  # Import Mask RCNN
  sys.path.append(ROOT_DIR)  # To find local version of the library
  from mrcnn import utils
  import mrcnn.model as modellib
  from mrcnn import visualize
  # Import COCO config
  sys.path.append("samples/coco/")  # To find local version
  import coco

  # Directory to save logs and trained model
  MODEL_DIR = os.path.join(ROOT_DIR, "logs")

  # Local path to trained weights file
  COCO_MODEL_PATH = os.path.join(ROOT_DIR, "mask_rcnn_coco.h5")
  # Download COCO trained weights from Releases if needed
  if not os.path.exists(COCO_MODEL_PATH):
      utils.download_trained_weights(COCO_MODEL_PATH)

  # Directory of images to run detection on
  IMAGE_DIR = os.path.join(ROOT_DIR, "images")

  class InferenceConfig(coco.CocoConfig):
    # Set batch size to 1 since we'll be running inference on
    # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1

  config = InferenceConfig()

  # Create model object in inference mode.
  rcnn_model = modellib.MaskRCNN(mode="inference", model_dir=MODEL_DIR, config=config)

  # Load weights trained on MS-COCO
  rcnn_model.load_weights(COCO_MODEL_PATH, by_name=True)

  # COCO Class names
  # Index of the class in the list is its ID. For example, to get ID of
  # the teddy bear class, use: class_names.index('teddy bear')
  class_names = ['BG', 'person', 'bicycle', 'car', 'motorcycle', 'airplane',
                 'bus', 'train', 'truck', 'boat', 'traffic light',
                 'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird',
                 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear',
                 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie',
                 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball',
                 'kite', 'baseball bat', 'baseball glove', 'skateboard',
                 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
                 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
                 'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza',
                 'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed',
                 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote',
                 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster',
                 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors',
                 'teddy bear', 'hair drier', 'toothbrush']

# ---------------------------------------- Helper functions for training ---------------------------------------- #
fx = 2304.5479
fy = 2305.8757
cx = 1686.2379
cy = 1354.9849

def pose_to_pixel(x, y, z):
  K = np.array([[fx, 0, cx],
                [0, fy, cy],
                [0, 0, 1]])

  R = np.array([[1, 0, 0, 0],
                [0, 1, 0, 0,],
                [0, 0, 1, 0]])

  W = np.array([[x], [y], [z], [1]])

  p = np.dot(np.dot(K, R), W)
  p_z = p/z
  return p_z

def load_Y_values(csv_filename):
  # Given a csv file, will return a Y matrix containing all the pose information
  # associated with each training example as well as a list of filenames
  with open(csv_filename, newline='') as csvfile:
    filenames = []
    reader = csv.reader(csvfile)
    data = list(reader)[1:]
    file_examples = []
    for i in range(len(data)):
      list_of_params = data[i][1].split()
      examples = []
      k = 0
      while k < len(list_of_params):
        pose = list_of_params[k+1:k+7]
        pose = [float(i) for i in pose]
        translation = pose[3:]
        eulers = pose[:3]
        # parameters are ordered roll, pitch, yaw (input dataset is yaw, pitch, roll)
        quaternion_rot = list(euler2quat(eulers[2], eulers[1], eulers[0]))
        examples.append(quaternion_rot + translation)
        k += 7

      examples = sorted(examples,key=lambda x: x[5])
      file_examples.append(examples)
      filenames.append(str(data[i][0]) + '.jpg')

    return file_examples, filenames

def extract_bounding_box_info(rcnn_model, filenames, file_examples, show_images = False):
  # Given a list of images, runs each image through the trained rcnn_model
  # to output a corresponding list of bounding box information for the
  # car closest to the camera for each image.
  car_class_id = class_names.index('car')
  X = np.zeros((len(filenames),1028))

  x_train = []
  y_train = []

  for k in range(len(filenames)):
    print("Loading image " + str(k))
    filename = filenames[k]
    # Load image
    image = skimage.io.imread(IMAGE_PATH + filename)
    if (os.path.exists(MASK_PATH + filename)):
      mask_image = skimage.io.imread(MASK_PATH + filename)
      mask = mask_image > 128
      image[mask] = 255

    height = image.shape[0]
    width = image.shape[1]
  
    # Run detection
    results = rcnn_model.detect([image])
    r = results[0]

    rois = r['rois']
    rois_with_index = []
    for i in range(len(rois)):
      rois_with_index.append((rois[i], i))
    rois = sorted(rois_with_index, key = lambda item : item[0][3],reverse=True)
    i = 0
    cars_in_file = file_examples[k]

    for ex in range(len(cars_in_file)):
      x = cars_in_file[ex][4]
      y = cars_in_file[ex][5]
      z = cars_in_file[ex][6]
      coordinates = pose_to_pixel(x, y, z)

      #normalize
      x_proj = (coordinates[0] - (width/2)) / (width/2)
      y_proj = (coordinates[1] - (height/2)) / (height/2)

      seen_cars = []

      for i in range(len(rois)):
        if i in seen_cars:
          continue
        index = rois[i][1]
        if r['class_ids'][index] == car_class_id:
          y1,x1,y2,x2 = rois[i][0]

          # normalize
          x1 = (x1 - (width/2)) / (width/2)
          x2 = (x2 - (width/2)) / (width/2)
          y1 = (y1 - (height/2)) / (height/2)
          y2 = (y2 - (height/2)) / (height/2)
          center_x = (x1 + x2) / 2
          center_y = (y1 + y2) / 2
          area = (x2 - x1) * (y2 - y1)
          width_to_height_ratio = (x2 - x1) / (y2 - y1)

          # Removes the camera car from consideration
          if not (y2 > 0.9 and center_x >= -.5 and center_x <= 0.5):
            if x_proj > x1 and x_proj < x2 and y_proj > y1 and y_proj < y2:
              bounding_box = np.asarray([x1, x2, y1, y2, center_x, center_y, area, width_to_height_ratio])
              feature_vec = r['features'][index].flatten()

              tr_example = np.concatenate([bounding_box, feature_vec])
              x_train.append(tr_example)
              y_train.append(np.asarray(cars_in_file[ex]))
              seen_cars.append(i)
              break

    print("Processed image " + str(k) + " and " + str(len(x_train)) + " cars.")
    
  X = np.asarray(x_train).T
  Y = np.asarray(y_train).T
          
        

  return X, Y

# ---------------------------------------- Displaying Pose in 2D Image ---------------------------------------- #
# Code largely pulled from this notebook:
# https://www.kaggle.com/zstusnoopy/visualize-the-location-and-3d-bounding-box-of-car

# convert euler angle to rotation matrix
def euler_to_Rot(yaw, pitch, roll):
    Y = np.array([[cos(yaw), 0, sin(yaw)],
                  [0, 1, 0],
                  [-sin(yaw), 0, cos(yaw)]])
    P = np.array([[1, 0, 0],
                  [0, cos(pitch), -sin(pitch)],
                  [0, sin(pitch), cos(pitch)]])
    R = np.array([[cos(roll), -sin(roll), 0],
                  [sin(roll), cos(roll), 0],
                  [0, 0, 1]])
    return np.dot(Y, np.dot(P, R))

def draw_line(image, points):
    color = (255, 0, 0)
    cv2.line(image, tuple(points[1][:2]), tuple(points[2][:2]), color, 16)
    cv2.line(image, tuple(points[1][:2]), tuple(points[4][:2]), color, 16)

    cv2.line(image, tuple(points[1][:2]), tuple(points[5][:2]), color, 16)
    cv2.line(image, tuple(points[2][:2]), tuple(points[3][:2]), color, 16)
    cv2.line(image, tuple(points[2][:2]), tuple(points[6][:2]), color, 16)
    cv2.line(image, tuple(points[3][:2]), tuple(points[4][:2]), color, 16)
    cv2.line(image, tuple(points[3][:2]), tuple(points[7][:2]), color, 16)

    cv2.line(image, tuple(points[4][:2]), tuple(points[8][:2]), color, 16)
    cv2.line(image, tuple(points[5][:2]), tuple(points[8][:2]), color, 16)

    cv2.line(image, tuple(points[5][:2]), tuple(points[6][:2]), color, 16)
    cv2.line(image, tuple(points[6][:2]), tuple(points[7][:2]), color, 16)
    cv2.line(image, tuple(points[7][:2]), tuple(points[8][:2]), color, 16)
    return image


def draw_points(image, points):
    image = np.array(image)
    for (p_x, p_y, p_z) in points:
        # print("p_x, p_y", p_x, p_y)
        cv2.circle(image, (p_x, p_y), 5, (255, 0, 0), -1)
    return image

def visualize_poses(poses):
	
	car_poses = []

	for pose in poses:
		quat = pose[:4]
		roll, pitch, yaw = quat2euler(quat)
		
		car_poses.append((yaw, pitch, roll, pose[4], pose[5], pose[6]))

	x_l = 1.02
	y_l = 0.80
	z_l = 2.31
	for yaw, pitch, roll, x, y, z in car_poses:
	    # I think the pitch and yaw should be exchanged
	    yaw, pitch, roll = -pitch, -yaw, -roll
	    Rt = np.eye(4)
	    t = np.array([x, y, z])
	    Rt[:3, 3] = t
	    Rt[:3, :3] = euler_to_Rot(yaw, pitch, roll).T
	    Rt = Rt[:3, :]
	    P = np.array([[0, 0, 0, 1],
	                  [x_l, y_l, -z_l, 1],
	                  [x_l, y_l, z_l, 1],
	                  [-x_l, y_l, z_l, 1],
	                  [-x_l, y_l, -z_l, 1],
	                  [x_l, -y_l, -z_l, 1],
	                  [x_l, -y_l, z_l, 1],
	                  [-x_l, -y_l, z_l, 1],
	                  [-x_l, -y_l, -z_l, 1]]).T
	    img_cor_points = np.dot(k, np.dot(Rt, P))
	    img_cor_points = img_cor_points.T
	    img_cor_points[:, 0] /= img_cor_points[:, 2]
	    img_cor_points[:, 1] /= img_cor_points[:, 2]
	    img_cor_points = img_cor_points.astype(int)
	    img = draw_points(img, img_cor_points)
	    img = draw_line(img, img_cor_points)
	    
	img = Image.fromarray(img)
	plt.imshow(img)
	plt.show()

# ---------------------------------------- Model Implementation ---------------------------------------- #
import tensorflow as tf
from tensorflow.python.framework import ops

# placeholders x y, forward prop z1, cost function mse loss = tf.reduce_mean(tf.squared_difference(prediction, Y)) 
# loss = tf.nn.l2_loss(prediction - Y),
# backprop tf.train.Adamoptimizer

def create_placeholders(n_x, n_y):

   
    X = tf.placeholder(dtype = tf.float32, shape=[n_x, None], name ='X')
    Y = tf.placeholder(dtype = tf.float32, shape=[n_y, None], name ='Y')
   
    
    return X, Y

def initialize_parameters():
                     
    W1 = tf.get_variable("W1", [1024,1032], initializer = tf.contrib.layers.xavier_initializer())
    b1 = tf.get_variable("b1", [1024,1], initializer = tf.zeros_initializer())
    W2 = tf.get_variable("W2", [1024,1024], initializer = tf.contrib.layers.xavier_initializer())
    b2 = tf.get_variable("b2", [1024,1], initializer = tf.zeros_initializer())
    W3 = tf.get_variable("W3", [4,1024], initializer = tf.contrib.layers.xavier_initializer())
    b3 = tf.get_variable("b3", [4,1], initializer = tf.zeros_initializer())

    W4 = tf.get_variable("W4", [100,8], initializer = tf.contrib.layers.xavier_initializer())
    b4 = tf.get_variable("b4", [100,1], initializer = tf.zeros_initializer())
    W5 = tf.get_variable("W5", [100,100], initializer = tf.contrib.layers.xavier_initializer())
    b5 = tf.get_variable("b5", [100,1], initializer = tf.zeros_initializer())
    W6 = tf.get_variable("W6", [100,1024], initializer = tf.contrib.layers.xavier_initializer())
    b6 = tf.get_variable("b6", [100,1], initializer = tf.zeros_initializer())
    W7 = tf.get_variable("W7", [3,200], initializer = tf.contrib.layers.xavier_initializer())
    b7 = tf.get_variable("b7", [3,1], initializer = tf.zeros_initializer())

    parameters = {"W1": W1,
                  "b1": b1,
                  "W2": W2,
                  "b2": b2,
                  "W3": W3,
                  "b3": b3,
                  "W4": W4,
                  "b4": b4,
                  "W5": W5,
                  "b5": b5,
                  "W6": W6,
                  "b6": b6,
                  "W7": W7,
                  "b7": b7}
    
    return parameters

def forward_propagation(X, parameters):
     
    W1 = parameters['W1']
    b1 = parameters['b1']
    W2 = parameters['W2']
    b2 = parameters['b2']
    W3 = parameters['W3']
    b3 = parameters['b3']

    W4 = parameters['W4']
    b4 = parameters['b4']
    W5 = parameters['W5']
    b5 = parameters['b5']
    W6 = parameters['W6']
    b6 = parameters['b6']
    W7 = parameters['W7']
    b7 = parameters['b7']

    Xr = X
    Xt = X[:8]

    Z1 = tf.add(tf.matmul(W1, Xr), b1)
    A1 = tf.tanh(Z1)   
    Z2 = tf.add(tf.matmul(W2, A1), b2)
    A2 = tf.nn.relu(Z2)
    Z3 = tf.add(tf.matmul(W3, A2), b3)

    Z4 = tf.add(tf.matmul(W4, Xt), b4)
    A4 = tf.tanh(Z4)
    Z5 = tf.add(tf.matmul(W5, A4), b5)
    A5 = tf.nn.relu(Z5)
    Z6 = tf.add(tf.matmul(W6, A2), b6)
    A6 = tf.nn.relu(Z6)
    concat = tf.concat([A5, A6], axis = 0)
    Z7 = tf.add(tf.matmul(W7, concat), b7)


    Y_hat = tf.concat([Z3, Z7], axis = 0)

                                                
    return Y_hat

def compute_cost(Z3, Y, alpha = 0.5, threshold = 2.8):
  
    t_hat = Z3[4:7]
    t = Y[4:7]

    huber_loss = tf.keras.losses.Huber(delta=threshold)
    t_cost = huber_loss(t, t_hat)
    #  tf.cond(tf.norm(t - t_hat) < threshold, lambda: tf.squared_difference(t, t_hat), lambda : tf.norm(t - t_hat) - (0.5 * threshold))

    r_hat = Z3[:4]
    r = Y[:4]

    r_cost = tf.squared_difference(r, r_hat)

    cost = tf.reduce_mean(((1-alpha) * t_cost) + (alpha * r_cost))
    #cost = tf.reduce_mean(tf.nn.cross_entropy_with_logits(logits = logits, labels = labels))
    
    return cost

def eval_accuracy(X, Y, Y_hat, X_train, Y_train, X_test, Y_test, t_treshold, r_threshold):
  correct_rot = tf.cast(tf.less(tf.square(tf.norm(Y[:4] - Y_hat[:4], axis = 0)), [r_threshold]), "float")
  correct_trans = tf.cast(tf.less(tf.square(tf.norm(Y[4:] - Y_hat[4:], axis = 0)), [t_treshold]), "float")
  t_accuracy = tf.reduce_mean(tf.cast(correct_trans, "float"))
  r_accuracy = tf.reduce_mean(tf.cast(correct_rot, "float"))
  accuracy = tf.reduce_mean(tf.cast(correct_trans * correct_rot, "float"))

  print('\n--------------')
  print("Evaluating accuracy with rotation threshold of " + str(r_threshold) + " and translation treshold of " + str(t_treshold))
  print('')
  print ("Train Accuracy:", accuracy.eval({X: X_train, Y: Y_train}))
  print ("Test Accuracy:", accuracy.eval({X: X_test, Y: Y_test}))
  print('')

  print ("Train Accuracy on just translation:", t_accuracy.eval({X: X_train, Y: Y_train}))
  print ("Test Accuracy on just translation:", t_accuracy.eval({X: X_test, Y: Y_test}))
  print('')

  print ("Train Accuracy on just rotation:", r_accuracy.eval({X: X_train, Y: Y_train}))
  print ("Test Accuracy on just rotation:", r_accuracy.eval({X: X_test, Y: Y_test}))
  print('\n--------------')

def pose_model(X_train, Y_train, X_test, Y_test, learning_rate = 0.001,
          num_epochs = 1000, print_cost = True):
    
    
    ops.reset_default_graph()                         # to be able to rerun the model without overwriting tf variables
    (n_x, m) = X_train.shape                          # (n_x: input size, m : number of examples in the train set)
    n_y = Y_train.shape[0]                            # n_y : output size
    costs = []                                        # To keep track of the cost
    
  
    X, Y = create_placeholders(n_x, n_y)
    parameters = initialize_parameters()
    Y_hat = forward_propagation(X, parameters)
    cost = compute_cost(Y_hat, Y)
    optimizer = tf.train.AdamOptimizer(learning_rate = learning_rate).minimize(cost)
  
    init = tf.global_variables_initializer()

    saver = tf.train.Saver()
  
    with tf.Session() as sess:
        
        
        sess.run(init)
        
        
        for epoch in range(num_epochs):

            epoch_cost = 0.                       
             
            seed = seed + 1
            

            #for minibatch in minibatches:

                #(minibatch_X, minibatch_Y) = minibatch
                
            _ , minibatch_cost = sess.run([optimizer, cost], feed_dict={X: X_train, Y: Y_train})

                
                #epoch_cost += minibatch_cost / minibatch_size

            if print_cost == True and epoch % 100 == 0:
                print ("Cost after epoch %i: %f" % (epoch, minibatch_cost))
            if print_cost == True and epoch >= 1000 and epoch % 5 == 0:
                costs.append(minibatch_cost)

            saved_path = saver.save(sess, './pose-model')
                
        
        plt.plot(np.squeeze(costs))
        plt.ylabel('cost')
        plt.xlabel('iterations (per fives)')
        plt.title("Learning rate =" + str(learning_rate))
        plt.show()

        
        parameters = sess.run(parameters)



        print ("Parameters have been trained!")

        eval_accuracy(X, Y, Y_hat, X_train, Y_train, X_test, Y_test, 2.7, 0.8)
        eval_accuracy(X, Y, Y_hat, X_train, Y_train, X_test, Y_test, 1, 0.5)
        eval_accuracy(X, Y, Y_hat, X_train, Y_train, X_test, Y_test, 5, 0.8)


        
        return parameters

def detect(image_path, model_path):
	image = skimage.io.imread(image_path)

    height = image.shape[0]
    width = image.shape[1]
  
    # Run detection through Mask-RCNN
    results = rcnn_model.detect([image])
    r = results[0]
    rois = r['rois']
    car_inputs = []

    for i in range(len(rois)):
    	if r['class_ids'][i] == car_class_id:
    		y1,x1,y2,x2 = rois[i][0]

		# normalize
		x1 = (x1 - (width/2)) / (width/2)
		x2 = (x2 - (width/2)) / (width/2)
		y1 = (y1 - (height/2)) / (height/2)
		y2 = (y2 - (height/2)) / (height/2)
		center_x = (x1 + x2) / 2
		center_y = (y1 + y2) / 2
		area = (x2 - x1) * (y2 - y1)
		width_to_height_ratio = (x2 - x1) / (y2 - y1)

		# Removes the camera car from consideration
		if not (y2 > 0.9 and center_x >= -.5 and center_x <= 0.5):
			bounding_box = np.asarray([x1, x2, y1, y2, center_x, center_y, area, width_to_height_ratio])
			feature_vec = r['features'][index].flatten()

			tr_example = np.concatenate([bounding_box, feature_vec])
			car_inputs.append(tr_example)

	X = np.asarray(car_inputs).T

	# Run through trained model
	poses = run_model(X, model_path)
	visualize_poses(poses)

def run_model(X, model_path):
	ops.reset_default_graph()
    (n_x, m) = X.shape
    
  
    X = create_placeholders(n_x)
    parameters = initialize_parameters()
    Y = forward_propagation(X, parameters)
  
    init = tf.global_variables_initializer()

    saver = tf.train.Saver()

    with tf.Session() as sess:


def main():
  args = sys.argv[1:]

  if len(args) == 4:
    if args[0] == '-preprocess':
      init_maskrcnn()
      train_file = args[1]
      test_file = args[2]
      out_file = args[3]
      tr_file_examples, tr_filenames = load_Y_values(TRAIN_CSV)
      X_train, Y_train = extract_bounding_box_info(rcnn_model, tr_filenames, tr_file_examples)

      test_file_examples, test_filenames = load_Y_values(TEST_CSV)
      X_test, Y_test = extract_bounding_box_info(rcnn_model, test_filenames, test_file_examples)

      np.savetxt(out_file + '_ytrain.csv', Y_train, delimiter = ',')
      np.savetxt(out_file + '_xtrain.csv', X_train, delimiter = ',')
      np.savetxt(out_file + '_ytest.csv', Y_test, delimiter = ',')
      np.savetxt(out_file + '_xtest.csv', X_test, delimiter = ',')

  if len(args) == 3:
    if args[0] == '-train':
      in_file = args[1]
      out_file = args[2]
      print('Loading training data files...\n')

      Y_train = np.loadtxt(in_file + '_ytrain.csv', delimiter = ',')
      X_train = np.loadtxt(in_file + '_xtrain.csv', delimiter = ',')
      Y_test = np.loadtxt(in_file + '_ytest.csv', delimiter = ',')
      X_test = np.loadtxt(in_file + '_xtest.csv', delimiter = ',')
      print('Files loaded!')
      print('Training model...')

      parameters = pose_model(X_train, Y_train, X_test, Y_test, learning_rate = 0.001, num_epochs = 10000)

  if args[0] == '-detect':





if __name__ == "__main__": 
	main()
