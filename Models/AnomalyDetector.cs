namespace PrismCore.Models;

/// <summary>在线异常检测器：Half-Space Trees（主）+ EWMA+Z-score（降级）。对照 anomaly.py。</summary>
public class AnomalyDetector
{
    private readonly double _alpha;
    private readonly double _zThreshold;
    private readonly int _minSamples;
    private int _n;
    private double _mean, _var, _lastScore;
    private readonly HalfSpaceTrees? _hst;

    public AnomalyDetector(double alpha = 0.3, double zThreshold = 3.0, int minSamples = 10, bool useHst = true)
    {
        _alpha = alpha;
        _zThreshold = zThreshold;
        _minSamples = minSamples;
        if (useHst)
            try { _hst = new HalfSpaceTrees(); } catch { /* 降级到 EWMA */ }
    }

    public double Update(double value)
    {
        _n++;
        if (_n == 1) { _mean = value; _var = 0; _lastScore = 0; return 0; }

        var delta1 = value - _mean;
        _mean += _alpha * delta1;
        var delta2 = value - _mean;
        _var = (1 - _alpha) * _var + _alpha * delta1 * delta2;

        if (_hst != null)
        {
            var raw = _hst.Score(value);
            _lastScore = raw > 0.5 ? raw * _zThreshold / 0.5 : 0.0;
        }
        else
        {
            if (_n < _minSamples || _var <= 0) { _lastScore = 0; return 0; }
            var std = Math.Sqrt(_var);
            _lastScore = std > 0 ? Math.Abs(value - _mean) / std : 0;
        }

        return _lastScore;
    }

    public bool IsAnomaly => _lastScore > _zThreshold;

    /// <summary>Half-Space Trees 流式异常检测。</summary>
    private sealed class HalfSpaceTrees
    {
        private readonly Tree[] _trees;
        private readonly int _windowSize;
        private int _count;

        public HalfSpaceTrees(int nTrees = 10, int height = 6, int windowSize = 50, int seed = 42)
        {
            _windowSize = windowSize;
            var rng = new Random(seed);
            _trees = new Tree[nTrees];
            for (int i = 0; i < nTrees; i++)
                _trees[i] = new Tree(height, 0.0, 100.0, rng);
        }

        public double Score(double value)
        {
            _count++;
            double sum = 0;
            for (int i = 0; i < _trees.Length; i++)
                sum += _trees[i].Insert(value);

            if (_count % _windowSize == 0)
                for (int i = 0; i < _trees.Length; i++)
                    _trees[i].Swap();

            return _count < _windowSize ? 0 : sum / _trees.Length;
        }

        private sealed class Tree
        {
            private readonly Node _root;

            public Tree(int height, double min, double max, Random rng)
                => _root = Build(height, min, max, rng);

            private static Node Build(int depth, double min, double max, Random rng)
            {
                var n = new Node();
                if (depth <= 0 || max - min < 1e-10) return n;
                n.Split = min + rng.NextDouble() * (max - min);
                n.L = Build(depth - 1, min, n.Split, rng);
                n.R = Build(depth - 1, n.Split, max, rng);
                return n;
            }

            public double Insert(double v) => InsertAt(_root, v);

            private static double InsertAt(Node n, double v)
            {
                n.Latest++;
                if (n.L == null) return n.Ref == 0 ? 1.0 : 1.0 / (1.0 + n.Ref);
                return v < n.Split ? InsertAt(n.L, v) : InsertAt(n.R!, v);
            }

            public void Swap() => SwapAt(_root);

            private static void SwapAt(Node n)
            {
                n.Ref = n.Latest;
                n.Latest = 0;
                if (n.L != null) { SwapAt(n.L); SwapAt(n.R!); }
            }

            private sealed class Node
            {
                public double Split;
                public Node? L, R;
                public int Ref, Latest;
            }
        }
    }
}
