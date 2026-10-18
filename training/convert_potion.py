import json, struct, sys, numpy as np, pathlib
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
raw = (src / "model.safetensors").read_bytes()
n = struct.unpack("<Q", raw[:8])[0]; header = json.loads(raw[8:8 + n]); print({k: (v["dtype"], v["shape"]) for k, v in header.items() if k != "__metadata__"})
name = [k for k in header if k != "__metadata__"][0]; h = header[name]
a, b = h["data_offsets"]
E = np.frombuffer(raw[8 + n + a: 8 + n + b], dtype={"F32": np.float32, "F16": np.float16}[h["dtype"]]).reshape(h["shape"]).astype(np.float32)
tok = json.loads((src / "tokenizer.json").read_text())
print(tok["model"]["type"], tok["normalizer"]["type"] if tok.get("normalizer") else None, tok["pre_tokenizer"]["type"], tok["model"].get("continuing_subword_prefix"), tok["model"].get("unk_token"))
vocab = tok["model"]["vocab"]; inv = sorted(vocab.items(), key=lambda kv: kv[1])
assert len(inv) == E.shape[0], (len(inv), E.shape)
scale = np.abs(E).max(axis=1, keepdims=True) / 127.0; scale[scale == 0] = 1
Q = np.round(E / scale).astype(np.int8)
out.mkdir(parents=True, exist_ok=True)
np.save(out / "potion8m_int8.npy", Q); np.save(out / "potion8m_scale.npy", scale.astype(np.float32))
(out / "potion8m_vocab.txt").write_text("\n".join(w for w, _ in inv))
err = np.abs(Q * scale - E).mean() / np.abs(E).mean(); print("int8 rel err", err)
