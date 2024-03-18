/*#include <iostream>>
using namespace std;

int main(){
    cout<<"My program";
    return 0;
}

#include <iostream>>
using namespace std;

int main() {
int number = 0;
auto &n = number; // n - ссылка на number
cout << n <<endl; // выведет 10
n = 20;
cout << n << '\n'; // выведет 20
cout << (&n == &n) << '\n'; // выведет 1, т.е. истина
}

#include <iostream>
 using namespace std;

class Person
{
public:
    void print() const
    {
        cout<< "Name: " << name << "\tAge: " << age <<endl;
    }
    string name;       //  имя
    unsigned age;           // возраст
};
class Employee : public Person
{
public:
    string company;    // компания
};
 
int main()
{
    Person tom;
    tom.name = "Tom";
    tom.age = 23;
    tom.print();    // Name: Tom       Age: 23
  
    Employee bob;
    bob.name = "Bob";
    bob.age = 31;
    bob.company = "Microsoft";
    bob.print();    // Name: Bob       Age: 31
}
*/