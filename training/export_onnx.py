import torch # type: ignore
import os
import sys
import argparse

# Fix Windows console encoding for ONNX emojis
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Ensure xapp is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def export_to_onnx(model_path: str, output_path: str):
    print(f"Loading PyTorch model from {model_path}...")
    # This assumes the model is a state_dict or full model.
    # For demonstration, we assume we can instantiate the model and load state_dict
    try:
        from xapp.model.lstm_autoencoder import LSTMAutoencoder
        model = LSTMAutoencoder()
        model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
        model.eval()
        # Remove data-dependent hook that breaks ONNX tracing
        model.bottleneck._forward_hooks.clear()
    except Exception as e:
        print(f"Could not load model structure. Error: {e}")
        return

    # 30 sequence length, 6 features
    dummy_input = torch.randn(1, 30, 6)
    
    print(f"Exporting to {output_path}...")
    torch.onnx.export(
        model, 
        dummy_input, 
        output_path, 
        export_params=True, 
        opset_version=11, 
        do_constant_folding=True, 
        input_names=['input'], 
        output_names=['output'],
        dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
    print("Standard ONNX export successful.")
    
    # Optional: Dynamic INT8 Quantization for Edge RIC
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType # type: ignore
        quantized_output_path = output_path.replace(".onnx", "_quantized.onnx")
        print(f"Applying INT8 dynamic quantization to {quantized_output_path}...")
        quantize_dynamic(
            model_input=output_path,
            model_output=quantized_output_path,
            weight_type=QuantType.QInt8,
        )
        print("Quantized ONNX export successful.")
    except ImportError:
        print("onnxruntime.quantization not found. Skipping INT8 quantization.")
    except Exception as e:
        print(f"Quantization failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="xapp/model/saved_models/lstm_ae_best.pt")
    parser.add_argument("--output", default="xapp/model/saved_models/lstm_ae_best.onnx")
    args = parser.parse_args()
    
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    export_to_onnx(args.model, args.output)
