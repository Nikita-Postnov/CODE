import math

class GeometryCalculator:

    def circle_area(radius):
        if radius < 0:
            raise ValueError("Радиус не может быть отрицательным")
        return math.pi * radius ** 2

    def triangle_area(side1, side2, side3):
        if side1 < 0 or side2 < 0 or side3 < 0:
            raise ValueError("Длины сторон должны быть положительными")
        s = (side1 + side2 + side3) / 2
        return math.sqrt(s * (s - side1) * (s - side2) * (s - side3))

radius = float(input("Введите радиус круга: "))
circle_area = GeometryCalculator.circle_area(radius)
print("Площадь круга с радиусом", radius, ":", circle_area)

side1 = float(input("Введите длину первой стороны треугольника: "))
side2 = float(input("Введите длину второй стороны треугольника: "))
side3 = float(input("Введите длину третьей стороны треугольника: "))
triangle_area = GeometryCalculator.triangle_area(side1, side2, side3)
print("Площадь треугольника: ", triangle_area)