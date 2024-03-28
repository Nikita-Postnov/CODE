import unittest
import math

class Interview:
    @staticmethod
    def circle_area(radius):
        return math.pi * radius ** 2

    @staticmethod
    def triangle_area(side1, side2, side3):
        s = (side1 + side2 + side3) / 2
        return math.sqrt(s * (s - side1) * (s - side2) * (s - side3))

class TestGeometryCalculator(unittest.TestCase):
    def test_circle_area(self):
        self.assertAlmostEqual(Interview.circle_area(1), math.pi)
        self.assertAlmostEqual(Interview.circle_area(0), 0)
        self.assertAlmostEqual(Interview.circle_area(5), 25 * math.pi)

    def test_triangle_area(self):
        self.assertAlmostEqual(Interview.triangle_area(3, 4, 5), 6)
        self.assertAlmostEqual(Interview.triangle_area(6, 8, 10), 24)
        self.assertAlmostEqual(Interview.triangle_area(5, 5, 5), 10.825317547305485)

if __name__ == '__main__':
    unittest.main()