"""Train TRINETRA's emotion reader on GoEmotions over the frozen potion-base-8M token vectors."""
import sys, json, time, numpy as np, torch, torch.nn as nn
data_dir, backend, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, backend)
from app.core import embed
torch.manual_seed(0); np.random.seed(0)
LABELS = open(f"{data_dir}/emotions.txt").read().split()
def load(split):
    X, Y = [], []
    for line in open(f"{data_dir}/{split}.tsv", encoding="utf8"):
        t, l, _ = line.rstrip("\n").split("\t")
        y = np.zeros(len(LABELS), np.float32); y[[int(i) for i in l.split(",")]] = 1
        X.append(embed.tokens(t)[:64]); Y.append(y)
    return X, np.stack(Y)
t0 = time.time(); tr, dv, te = load("train"), load("dev"), load("test"); print("tokenised", round(time.time() - t0, 1), "s")
_, E = embed._model(); V = E.shape[0]
def pad(X):
    L = max(1, max(len(x) for x in X)); ids = np.zeros((len(X), L), np.int64); mask = np.zeros((len(X), L), np.float32)
    for i, x in enumerate(X): ids[i, :len(x)] = x; mask[i, :len(x)] = 1
    return torch.tensor(ids), torch.tensor(mask)
class Reader(nn.Module):
    def __init__(s, H=384):
        super().__init__()
        s.E = nn.Embedding.from_pretrained(torch.tensor(E), freeze=True)
        s.tw = nn.Embedding(V, 1); nn.init.zeros_(s.tw.weight)           # learned importance of each word piece
        s.q = nn.Parameter(torch.zeros(256))                             # and a learned attention query
        s.conv = nn.Conv1d(256, 256, 3, padding=1)                       # reads 3 word pieces at a time: "not that good"
        nn.init.zeros_(s.conv.weight); nn.init.zeros_(s.conv.bias)
        s.mlp = nn.Sequential(nn.Dropout(0.1), nn.Linear(512, H), nn.GELU(), nn.Dropout(0.2), nn.Linear(H, len(LABELS)))
    def forward(s, ids, mask):
        e = s.E(ids)
        e = e + torch.nn.functional.gelu(s.conv((e * mask.unsqueeze(-1)).transpose(1, 2)).transpose(1, 2)) * mask.unsqueeze(-1)
        a = (e @ s.q + s.tw(ids).squeeze(-1)).masked_fill(mask == 0, -1e9)
        att = torch.softmax(a, 1).unsqueeze(-1) * (mask.sum(1, keepdim=True) > 0).unsqueeze(-1)
        mean = (e * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True).clamp(min=1)
        return s.mlp(torch.cat([(e * att).sum(1), mean], 1) * 10)
m = Reader(); opt = torch.optim.AdamW(m.parameters(), lr=2e-3, weight_decay=1e-4)
pos = tr[1].mean(0); pw = torch.tensor(np.clip((1 - pos) / pos, 1, 30) ** 0.5)  # rare emotions count a bit more
lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
def predict(X):
    m.eval(); P = []
    with torch.no_grad():
        for i in range(0, len(X), 1024):
            ids, mask = pad(X[i:i + 1024]); P.append(torch.sigmoid(m(ids, mask)).numpy())
    m.train(); return np.concatenate(P)
def f1(P, Y, th):
    pr = P >= th; tp = (pr & (Y > 0)).sum(0); fp = (pr & (Y == 0)).sum(0); fn = (~pr & (Y > 0)).sum(0)
    return 2 * tp / np.maximum(2 * tp + fp + fn, 1)
best, best_state = -1, None
Xtr, Ytr = tr
for ep in range(14):
    perm = np.random.permutation(len(Xtr)); tl = 0
    for i in range(0, len(perm), 256):
        b = perm[i:i + 256]; ids, mask = pad([Xtr[j] for j in b])
        loss = lossf(m(ids, mask), torch.tensor(Ytr[b])); opt.zero_grad(); loss.backward(); opt.step(); tl += loss.item() * len(b)
    Pd = predict(dv[0]); score = f1(Pd, dv[1], 0.5).mean()
    print(f"epoch {ep} loss {tl / len(Xtr):.4f} dev macroF1@0.5 {score:.3f}")
    if score > best: best, best_state = score, {k: v.clone() for k, v in m.state_dict().items()}
m.load_state_dict(best_state)
Pd, Pt = predict(dv[0]), predict(te[0])
grid = np.linspace(0.05, 0.95, 37)
th = np.array([grid[np.argmax([f1(Pd[:, [k]], dv[1][:, [k]], g)[0] for g in grid])] for k in range(len(LABELS))])
ft = f1(Pt, te[1], th)
print("TEST macro-F1 (28 labels, tuned thresholds):", round(float(ft.mean()), 3))
for k in np.argsort(-ft): print(f"  {LABELS[k]:15s} {ft[k]:.2f}  th={th[k]:.2f}")
EKMAN = {"anger": ["anger", "annoyance", "disapproval"], "disgust": ["disgust"], "fear": ["fear", "nervousness"],
         "joy": ["joy", "amusement", "approval", "excitement", "gratitude", "love", "optimism", "relief", "pride", "admiration", "desire", "caring"],
         "sadness": ["sadness", "disappointment", "embarrassment", "grief", "remorse"], "surprise": ["surprise", "realization", "confusion", "curiosity"], "neutral": ["neutral"]}
def group(P, Y=None):
    idx = [[LABELS.index(l) for l in v] for v in EKMAN.values()]
    return np.stack([P[:, i].max(1) for i in idx], 1), (np.stack([Y[:, i].max(1) for i in idx], 1) if Y is not None else None)
Gd, Ydg = group(Pd / th * 0.5, dv[1]); Gt, Ytg = group(Pt / th * 0.5, te[1])
gth = np.array([grid[np.argmax([f1(Gd[:, [k]], Ydg[:, [k]], g)[0] for g in grid])] for k in range(len(EKMAN))])
fg = f1(Gt, Ytg, gth); print("TEST Ekman macro-F1:", round(float(fg.mean()), 3), dict(zip(EKMAN, np.round(fg, 2))))
sd = m.state_dict()
np.savez_compressed(out, conv_w=sd["conv.weight"].numpy(), conv_b=sd["conv.bias"].numpy(), tw=sd["tw.weight"].numpy().astype(np.float16).ravel(), q=sd["q"].numpy(),
                    W1=sd["mlp.1.weight"].numpy().T.copy(), b1=sd["mlp.1.bias"].numpy(), W2=sd["mlp.4.weight"].numpy().T.copy(), b2=sd["mlp.4.bias"].numpy(),
                    th=th.astype(np.float32), labels=np.array(LABELS))
json.dump({"test_macro_f1": float(ft.mean()), "test_ekman_f1": float(fg.mean()), "per_label": dict(zip(LABELS, map(float, ft)))}, open(out.replace(".npz", ".json"), "w"), indent=1)
