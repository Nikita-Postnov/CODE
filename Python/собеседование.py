import math

class CircleAreaStrategy:
    def calculate_area(radius):
        if radius < 0:
            raise ValueError("Радиус не может быть отрицательным")
        return math.pi * radius ** 2

class TriangleAreaStrategy:
    def calculate_area(side1, side2, side3):
        if side1 <= 0 or side2 <= 0 or side3 <= 0:
            raise ValueError("Длины сторон должны быть положительными")
        s = (side1 + side2 + side3) / 2
        return math.sqrt(s * (s - side1) * (s - side2) * (s - side3))

class GeometryCalculator:
    @staticmethod
    def calculate_area(shape, *args):
        if shape == "circle":
            return CircleAreaStrategy.calculate_area(*args)
        elif shape == "triangle":
            return TriangleAreaStrategy.calculate_area(*args)
        else:
            raise ValueError("Неизвестный тип фигуры")

# Юнит-тесты
def test_circle_area():
    assert round(GeometryCalculator.calculate_area("circle", 5), 2) == 78.54

def test_triangle_area():
    assert round(GeometryCalculator.calculate_area("triangle", 3, 4, 5), 2) == 6.0

# Проверка на прямоугольность треугольника
def is_right_triangle(side1, side2, side3):
    sides = [side1, side2, side3]
    max_side = max(sides)
    sides.remove(max_side)
    return math.isclose(max_side ** 2, sides[0] ** 2 + sides[1] ** 2)

radius = float(input("Введите радиус круга: "))
circle_area = GeometryCalculator.calculate_area("circle", radius)
print("Площадь круга:", circle_area)

side1 = float(input("Введите длину первой стороны треугольника: "))
side2 = float(input("Введите длину второй стороны треугольника: "))
side3 = float(input("Введите длину третьей стороны треугольника: "))
triangle_area = GeometryCalculator.calculate_area("triangle", side1, side2, side3)
print("Площадь треугольника: ", triangle_area)

if is_right_triangle(side1, side2, side3):
    print("Этот треугольник прямоугольный.")
else:
    print("Этот треугольник не прямоугольный.")
