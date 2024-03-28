import math

class Interview:
    @staticmethod
    def circle_area(radius):
        return math.pi * radius ** 2

    @staticmethod
    def triangle_area(side1, side2, side3):
        s = (side1 + side2 + side3) / 2
        return math.sqrt(s * (s - side1) * (s - side2) * (s - side3))

if __name__ == "__main__":
    radius = float(input("Введите радиус круга: "))
    print("Площадь круга:", Interview.circle_area(radius))

    side1 = float(input("Введите длину первой стороны треугольника: "))
    side2 = float(input("Введите длину второй стороны треугольника: "))
    side3 = float(input("Введите длину третьей стороны треугольника: "))
    print("Площадь треугольника:", Interview.triangle_area(side1, side2, side3))