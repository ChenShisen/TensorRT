#
# Copyright (c) 2021, NVIDIA CORPORATION. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import sys

# This sample uses an MNIST PyTorch model to create a TensorRT Inference Engine
import model
import numpy as np
import pycuda.autoinit
import tensorrt as trt

trt_version = trt.__version__
trt_v7 = True if trt_version.startswith("7") else False

sys.path.insert(1, os.path.join(sys.path[0], ".."))
import common

# You can set the logger severity higher to suppress messages (or lower to display more messages).
TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

class ModelData(object):
    INPUT_NAME = "data"
    INPUT_SHAPE = (1, 1, 28, 28)
    OUTPUT_NAME = "prob"
    OUTPUT_SIZE = 10
    DTYPE = trt.float32

def populate_network(network, weights):
    # Configure the network layers based on the weights provided.
    input_tensor = network.add_input(name=ModelData.INPUT_NAME, dtype=ModelData.DTYPE, shape=ModelData.INPUT_SHAPE)

    conv1_w = weights['conv1.weight'].cpu().numpy()
    conv1_b = weights['conv1.bias'].cpu().numpy()
    conv1 = network.add_convolution(input=input_tensor, num_output_maps=20, kernel_shape=(5, 5), kernel=conv1_w, bias=conv1_b)
    conv1.stride = (1, 1)

    pool1 = network.add_pooling(input=conv1.get_output(0), type=trt.PoolingType.MAX, window_size=(2, 2))
    pool1.stride = (2, 2)

    conv2_w = weights['conv2.weight'].cpu().numpy()
    conv2_b = weights['conv2.bias'].cpu().numpy()
    conv2 = network.add_convolution(pool1.get_output(0), 50, (5, 5), conv2_w, conv2_b)
    conv2.stride = (1, 1)

    pool2 = network.add_pooling(conv2.get_output(0), trt.PoolingType.MAX, (2, 2))
    pool2.stride = (2, 2)

    fc1_w = weights['fc1.weight'].cpu().numpy()
    fc1_b = weights['fc1.bias'].cpu().numpy()
    fc1 = network.add_fully_connected(input=pool2.get_output(0), num_outputs=500, kernel=fc1_w, bias=fc1_b)

    relu1 = network.add_activation(input=fc1.get_output(0), type=trt.ActivationType.RELU)

    fc2_w = weights['fc2.weight'].cpu().numpy()
    fc2_b = weights['fc2.bias'].cpu().numpy()
    fc2 = network.add_fully_connected(relu1.get_output(0), ModelData.OUTPUT_SIZE, fc2_w, fc2_b)

    fc2.get_output(0).name = ModelData.OUTPUT_NAME
    network.mark_output(tensor=fc2.get_output(0))


def build_engine(weights):
    # For more information on TRT basics, refer to the introductory samples.
    builder = trt.Builder(TRT_LOGGER)
    network = builder.create_network(common.EXPLICIT_BATCH)
    config = builder.create_builder_config()
    runtime = trt.Runtime(TRT_LOGGER)

    config.max_workspace_size = common.GiB(1)
    # Populate the network using weights from the PyTorch model.
    populate_network(network, weights)
    # Build and return an engine.
    
    if trt_v7:
        #plan = builder.build_cuda_engine(network)
        plan = builder.build_engine(network,config)
        return plan
    plan = builder.build_serialized_network(network, config)
    return runtime.deserialize_cuda_engine(plan)

# Loads a random test case from pytorch's DataLoader
def load_random_test_case(model, pagelocked_buffer):
    # Select an image at random to be the test case.
    img, expected_output = model.get_random_testcase()
    # Copy to the pagelocked input buffer
    np.copyto(pagelocked_buffer, img)
    return expected_output

def main():
    common.add_help(description="Runs an MNIST network using a PyTorch model")
    # Train the PyTorch model
    mnist_model = model.MnistModel()
    mnist_model.learn()
    weights = mnist_model.get_weights()
    # Do inference with TensorRT.
    engine = build_engine(weights)

    #save trt engine
    f = open("mnist.trt","wb")
    f.write(engine.serialize())
    f.close()

    #load trt engine
    f = open("mnist.trt","rb")
    engine = trt.Runtime(TRT_LOGGER)
    engine = engine.deserialize_cuda_engine(f.read())
    f.close()
    
    # Build an engine, allocate buffers and create a stream.
    # For more information on buffer allocation, refer to the introductory samples.
    inputs, outputs, bindings, stream = common.allocate_buffers(engine)
    context = engine.create_execution_context()

    case_num = load_random_test_case(mnist_model, pagelocked_buffer=inputs[0].host)
    # For more information on performing inference, refer to the introductory samples.
    # The common.do_inference function will return a list of outputs - we only have one in this case.
    [output] = common.do_inference_v2(context, bindings=bindings, inputs=inputs, outputs=outputs, stream=stream)
    pred = np.argmax(output)
    print("Test Case: " + str(case_num))
    print("Prediction: " + str(pred))

if __name__ == '__main__':
    main()
