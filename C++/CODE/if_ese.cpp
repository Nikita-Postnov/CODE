#include <iostream>
using namespace std;

int main(){
short int a, b;
cout<<"Enter a"<<endl;
cin>>a;
cout<<"Enter b"<<endl;
cin>>b;
if(a>b){
    cout<<"a is greater than b"<<endl;
    }
else if (b>a)
{
    cout<<"b is greater than a"<<endl;
}
else
{
    cout<<"a and b are equal"<<endl;
}
return 0;
}